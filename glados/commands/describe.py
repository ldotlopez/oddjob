"""Describe command: image -> NAME.description.txt via a Describer backend.

The system prompt comes from `[prompts] describe` in the config, with
-i/--instructions filling its `{instructions}`. Any text backend whose model
takes images implements it (tasks/text_backend.py). The same click.Command
is the `glados describe` subcommand and the standalone `describe` tool.
"""

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
from filejobs.inputs import expand_inputs
from filejobs.pipeline import Job, override_destination, suffix_destination
from glados.core.cli_common import (
    GladosContext,
    backend_option,
    logging_options,
    model_option,
    pass_glados_context,
)
from glados.tasks.describe import DESCRIPTION_EXTENSION, DescribeStep, is_image
from glados.tasks.protocols import Describer


@click.command("describe")
@paths_argument
@click.option(
    "-i",
    "--instructions",
    default=None,
    help="extra instructions, e.g. 'in Spanish' or 'one sentence'",
)
@model_option
@backend_option("describe")
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
    """Describe each image in PATH... into NAME.description.txt (needs a
    model that takes images)."""
    inputs = expand_inputs(paths, is_image)
    check_single_output(output, inputs)
    dest_fn = override_destination(output, suffix_destination(DESCRIPTION_EXTENSION))
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    prompt = ctx.config().prompts.render_describe(instructions)
    describer = ctx.backend("describe", Describer, backend, {"model": model})
    job = Job(steps=[(DescribeStep(describer, prompt), "Describing")], dest_fn=dest_fn)
    run_jobs(inputs, job_action(job, overwrite), "Describing")


if __name__ == "__main__":
    cli()
