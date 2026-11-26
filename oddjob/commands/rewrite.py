"""Rewrite command: text file -> rewritten text file via a Rewriter backend.

No task module of its own: a single filejobs.pipeline.TextStep driving the backend selected by
core/backends.py, with the system prompt rendered from `[prompts] rewrite`
in the config. Lands at infix_destination("rewrite"), so
file.txt -> file.rewrite.txt by default (see suffix_destination's docstring
for why it isn't safe here).
"""

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
from oddjob.lib.protocols import Rewriter

DEFAULT_INFIX = "rewrite"


@click.command("rewrite")
@paths_argument
@click.option(
    "-i",
    "--instructions",
    default=None,
    help="rewrite instructions, e.g. 'more formal tone'"
    " (default: improve clarity and correctness)",
)
@model_option
@backend_option("rewrite")
@same_format_options
@dry_run_option
@logging_options
@pass_session
def rewrite_cmd(
    session: Session,
    paths: tuple[Path, ...],
    instructions: str | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Rewrite each input in PATH... per --instructions."""

    def make_step() -> TextStep:
        prompt = session.config().prompts.render_rewrite(instructions)
        rewriter = session.backend("rewrite", Rewriter, backend, {"model": model})
        return TextStep(lambda text: rewriter.rewrite(text, prompt=prompt))

    run_same_format_jobs(
        paths,
        text_inputs_except_outputs(DEFAULT_INFIX),
        DEFAULT_INFIX,
        make_step,
        "Rewriting",
        output=output,
        overwrite=overwrite,
        in_place=in_place,
        keep_mtime=keep_mtime,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    rewrite_cmd()
