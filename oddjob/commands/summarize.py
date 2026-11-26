"""Summarize command: text file -> summary via a Summarizer backend. Same
shape as commands/rewrite.py; the prompt comes from `[prompts] summarize`."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    dry_run_option,
    paths_argument,
    run_same_format_jobs,
    same_format_options,
)
from filejobs.inputs import text_inputs_except_outputs
from filejobs.pipeline import TextStep
from oddjob.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_session,
)
from oddjob.core.session import Session
from oddjob.lib.protocols import Summarizer

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
@same_format_options
@dry_run_option
@logging_options
@pass_session
def summarize_cmd(
    session: Session,
    paths: tuple[Path, ...],
    max_length: int | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Summarize each input in PATH...."""

    def make_step() -> TextStep:
        prompt = session.config().prompts.render_summarize(max_length)
        summarizer = session.backend("summarize", Summarizer, backend, {"model": model})
        return TextStep(lambda text: summarizer.summarize(text, prompt=prompt))

    run_same_format_jobs(
        paths,
        text_inputs_except_outputs(DEFAULT_INFIX),
        DEFAULT_INFIX,
        make_step,
        "Summarizing",
        output=output,
        overwrite=overwrite,
        in_place=in_place,
        keep_mtime=keep_mtime,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    summarize_cmd()
