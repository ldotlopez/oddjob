"""Expand command: text file -> expanded text via an Expander backend. Same
shape as commands/rewrite.py; the prompt comes from `[prompts] expand`."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    check_single_output,
    dry_run_option,
    job_action,
    paths_argument,
    print_plan,
    run_jobs,
    same_format_destination,
    same_format_options,
)
from filejobs.inputs import expand_inputs, text_inputs_except_outputs
from filejobs.pipeline import Job, TextStep, infix_destination
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
    inputs = expand_inputs(paths, text_inputs_except_outputs(DEFAULT_INFIX))
    check_single_output(output, inputs)
    dest_fn = same_format_destination(
        output, in_place, infix_destination(DEFAULT_INFIX)
    )
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    prompt = session.config().prompts.render_expand(target_length)
    expander = session.backend("expand", Expander, backend, {"model": model})
    job = Job(
        steps=[
            (TextStep(lambda text: expander.expand(text, prompt=prompt)), "Expanding")
        ],
        dest_fn=dest_fn,
        keep_times=keep_mtime,
    )
    run_jobs(inputs, job_action(job, overwrite or in_place), "Expanding")


if __name__ == "__main__":
    expand_cmd()
