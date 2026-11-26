"""Expand command: text file -> expanded text via an Expander backend. Same
shape as commands/rewrite.py; the prompt comes from `[prompts] expand`."""

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
from oddjob.lib.protocols import Expander

DEFAULT_INFIX = "expanded"


@click.command("expand")
@paths_argument
@click.option(
    "--target-length",
    type=click.IntRange(min=1),
    default=None,
    help="approximate target length, in words",
)
@model_option
@backend_option("expand")
@same_format_options
@dry_run_option
@logging_options
@pass_session
def expand_cmd(
    session: Session,
    paths: tuple[Path, ...],
    target_length: int | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Expand each input in PATH... with more detail and examples."""

    def make_step() -> TextStep:
        prompt = session.config().prompts.render_expand(target_length)
        expander = session.backend("expand", Expander, backend, {"model": model})
        return TextStep(lambda text: expander.expand(text, prompt=prompt))

    run_same_format_jobs(
        paths,
        text_inputs_except_outputs(DEFAULT_INFIX),
        DEFAULT_INFIX,
        make_step,
        "Expanding",
        output=output,
        overwrite=overwrite,
        in_place=in_place,
        keep_mtime=keep_mtime,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    expand_cmd()
