"""Rewrite task: text file -> rewritten text file via a Rewriter backend.

A single core.pipeline.TextStep driving the backend selected by
core/backends.py, with the system prompt rendered from `[prompts] rewrite`
in the config. The same click.Command is the `glados rewrite` subcommand and
the standalone `rewrite` tool. Lands at infix_destination("rewrite"), so
file.txt -> file.rewrite.txt by default (see suffix_destination's docstring
for why it isn't safe here).
"""

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
    dry_run_option,
    job_action,
    paths_argument,
    print_plan,
    run_jobs,
)
from glados.core.inputs import expand_inputs, text_inputs_except_outputs
from glados.core.pipeline import Job, TextStep, infix_destination, override_destination
from glados.tasks.protocols import Rewriter

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
@common_file_options
@dry_run_option
@logging_options
@pass_glados_context
def cli(
    ctx: GladosContext,
    paths: tuple[Path, ...],
    instructions: str | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Rewrite each input in PATH... per --instructions."""
    inputs = expand_inputs(paths, text_inputs_except_outputs(DEFAULT_INFIX))
    check_single_output(output, inputs)
    dest_fn = override_destination(output, infix_destination(DEFAULT_INFIX))
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    prompt = ctx.config().prompts.render_rewrite(instructions)
    rewriter = ctx.backend("rewrite", Rewriter, backend, {"model": model})
    job = Job(
        steps=[
            (TextStep(lambda text: rewriter.rewrite(text, prompt=prompt)), "Rewriting")
        ],
        dest_fn=dest_fn,
    )
    run_jobs(inputs, job_action(job, overwrite), "Rewriting")


if __name__ == "__main__":
    cli()
