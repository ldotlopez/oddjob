"""Summarize command: text file -> summary via a Summarizer backend. Same
shape as commands/rewrite.py; the prompt comes from `[prompts] summarize`."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    check_single_output,
    common_file_options,
    dry_run_option,
    job_action,
    paths_argument,
    print_plan,
    run_jobs,
)
from filejobs.inputs import expand_inputs, text_inputs_except_outputs
from filejobs.pipeline import Job, TextStep, infix_destination, override_destination
from glados.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_glados,
)
from glados.core.session import Glados
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
@dry_run_option
@logging_options
@pass_glados
def cli(
    glados: Glados,
    paths: tuple[Path, ...],
    max_length: int | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Summarize each input in PATH...."""
    inputs = expand_inputs(paths, text_inputs_except_outputs(DEFAULT_INFIX))
    check_single_output(output, inputs)
    dest_fn = override_destination(output, infix_destination(DEFAULT_INFIX))
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    prompt = glados.config().prompts.render_summarize(max_length)
    summarizer = glados.backend("summarize", Summarizer, backend, {"model": model})
    job = Job(
        steps=[
            (
                TextStep(lambda text: summarizer.summarize(text, prompt=prompt)),
                "Summarizing",
            )
        ],
        dest_fn=dest_fn,
    )
    run_jobs(inputs, job_action(job, overwrite), "Summarizing")


if __name__ == "__main__":
    cli()
