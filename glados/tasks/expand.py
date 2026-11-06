"""Expand task — signatures and CLI shape only; no backend implements
Expander yet. Same shape as tasks/rewrite.py — see its module docstring
for the discovery/backend-resolution pattern."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from glados.core.cli_common import (
    GladosContext,
    backend_option,
    common_file_options,
    logging_options,
    model_option,
    pass_glados_context,
)
from glados.core.pipeline import Job, infix_destination, override_destination
from glados.core.progress import ProgressStream
from glados.tasks.protocols import Expander

DEFAULT_INFIX = "expanded"


class ExpandStep:
    """Will read `input_path`'s text, drive an Expander backend, and
    write the result to a temp file. Not implemented yet."""

    def __init__(self, backend: Expander, target_length: int | None) -> None:
        self.backend = backend
        self.target_length = target_length

    def run(self, input_path: Path) -> ProgressStream[Path]:
        raise NotImplementedError("ExpandStep is not implemented yet")
        yield  # pragma: no cover


@click.command("expand")
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option(
    "--target-length",
    type=int,
    default=None,
    help="approximate target length (unit is backend-defined)",
)
@model_option
@backend_option("expand")
@common_file_options
@logging_options
@pass_glados_context
def cli(
    ctx: GladosContext,
    input_path: Path,
    target_length: int | None,
    model: Path | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Expand INPUT_PATH. Not yet implemented."""
    backend_instance = ctx.backend("expand", Expander, backend, {"model": model})
    job = Job(
        steps=[(ExpandStep(backend_instance, target_length), "Expanding")],
        dest_fn=override_destination(output, infix_destination(DEFAULT_INFIX)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
