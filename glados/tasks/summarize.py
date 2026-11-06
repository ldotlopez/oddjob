"""Summarize task — signatures and CLI shape only; no backend implements
Summarizer yet. Same shape as tasks/rewrite.py — see its module docstring
for the discovery/backend-resolution pattern."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from glados.core.backend_discovery import backends_for
from glados.core.cli_common import (
    GladosContext,
    backend_option,
    common_file_options,
    model_option,
    pass_glados_context,
)
from glados.core.pipeline import Job, infix_destination, override_destination
from glados.core.progress import ProgressStream
from glados.tasks.protocols import Summarizer

DEFAULT_INFIX = "summary"


class SummarizeStep:
    """Will read `input_path`'s text, drive a Summarizer backend, and
    write the result to a temp file. Not implemented yet."""

    def __init__(self, backend: Summarizer, max_length: int | None) -> None:
        self.backend = backend
        self.max_length = max_length

    def run(self, input_path: Path) -> ProgressStream[Path]:
        raise NotImplementedError("SummarizeStep is not implemented yet")
        yield  # pragma: no cover


# Discovered via foundation.plugin.Register — empty today since no backend
# implements Summarizer yet (see core/backend_discovery.py). Once one does,
# this dict populates automatically; no code here needs to change.
_DEFAULT_BACKENDS: dict[str, Summarizer] = backends_for(Summarizer)
DEFAULT_BACKEND: str | None = None


@click.command("summarize")
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option(
    "--max-length",
    type=int,
    default=None,
    help="approximate cap on summary length (unit is backend-defined)",
)
@model_option
@backend_option(_DEFAULT_BACKENDS, DEFAULT_BACKEND)
@common_file_options
@pass_glados_context
def cli(
    ctx: GladosContext,
    input_path: Path,
    max_length: int | None,
    model: Path | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Summarize INPUT_PATH. Not yet implemented."""
    if not _DEFAULT_BACKENDS:
        raise click.ClickException("summarize task has no backend implemented yet")
    backend_instance = _DEFAULT_BACKENDS[backend]
    job = Job(
        steps=[(SummarizeStep(backend_instance, max_length), "Summarizing")],
        dest_fn=override_destination(output, infix_destination(DEFAULT_INFIX)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
