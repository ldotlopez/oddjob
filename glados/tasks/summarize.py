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
from glados.core.cli_options import (
    check_single_output,
    common_file_options,
    paths_argument,
    run_jobs,
)
from glados.core.inputs import expand_inputs, text_inputs_except_outputs
from glados.core.pipeline import Job, TextStep, infix_destination, override_destination
from glados.tasks.protocols import Summarizer

DEFAULT_INFIX = "summary"


@click.command("summarize")
@paths_argument
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
    paths: tuple[Path, ...],
    max_length: int | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Summarize each input in PATH...."""
    inputs = expand_inputs(paths, text_inputs_except_outputs(DEFAULT_INFIX))
    check_single_output(output, inputs)
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
    run_jobs(job, inputs, overwrite, "Summarizing")


if __name__ == "__main__":
    cli()
