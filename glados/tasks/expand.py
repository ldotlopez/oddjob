"""Expand task: text file -> expanded text via an Expander backend. Same
shape as tasks/rewrite.py; the prompt comes from `[prompts] expand`."""

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
from glados.core.pipeline import Job, TextStep, infix_destination, override_destination
from glados.tasks.protocols import Expander

DEFAULT_INFIX = "expanded"


@click.command("expand")
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option(
    "--target-length",
    type=click.IntRange(min=1),
    default=None,
    help="approximate target length, in words",
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
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Expand INPUT_PATH with more detail and examples."""
    prompt = ctx.config().prompts.render_expand(target_length)
    expander = ctx.backend("expand", Expander, backend, {"model": model})
    job = Job(
        steps=[
            (TextStep(lambda text: expander.expand(text, prompt=prompt)), "Expanding")
        ],
        dest_fn=override_destination(output, infix_destination(DEFAULT_INFIX)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
