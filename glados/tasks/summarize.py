"""Summarize task: text file -> summary via a Summarizer backend. Same
shape as tasks/rewrite.py; the prompt comes from `[prompts] summarize`."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from glados.core.cli_common import (
    GladosContext,
    backend_option,
    logging_options,
    model_option,
    pass_glados_context,
)
from glados.core.cli_options import common_file_options
from glados.core.pipeline import Job, TextStep, infix_destination, override_destination
from glados.tasks.protocols import Summarizer

DEFAULT_INFIX = "summary"


@click.command("summarize")
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option(
    "--max-length",
    type=click.IntRange(min=1),
    default=None,
    help="approximate cap on summary length, in words",
)
@model_option
@backend_option("summarize")
@common_file_options
@logging_options
@pass_glados_context
def cli(
    ctx: GladosContext,
    input_path: Path,
    max_length: int | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Summarize INPUT_PATH."""
    prompt = ctx.config().prompts.render_summarize(max_length)
    summarizer = ctx.backend("summarize", Summarizer, backend, {"model": model})
    job = Job(
        steps=[
            (
                TextStep(lambda text: summarizer.summarize(text, prompt=prompt)),
                "Summarizing",
            )
        ],
        dest_fn=override_destination(output, infix_destination(DEFAULT_INFIX)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
