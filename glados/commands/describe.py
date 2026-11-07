"""Describe command: print a description of each image, or with -w/--write
land it at NAME.description.txt, via a Describer backend.

The system prompt comes from `[prompts] describe` in the config, with
-i/--instructions filling its `{instructions}`. Any text backend whose model
takes images implements it (tasks/text_backend.py). Printing is a report
under run_batch; writing is a file producer (Job + run_jobs), so -o, -y and
-n apply only then. The same click.Command is the `glados describe`
subcommand and the standalone `describe` tool.
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.batch import run_batch
from filejobs.cli_options import (
    check_single_output,
    common_file_options,
    dry_run_option,
    finish_batch,
    job_action,
    paths_argument,
    print_plan,
    run_jobs,
)
from filejobs.inputs import expand_inputs
from filejobs.pipeline import Job, override_destination, suffix_destination
from filejobs.progress import BaseProgressReporter
from glados.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_glados,
)
from glados.core.session import Glados
from glados.tasks.describe import (
    DESCRIPTION_EXTENSION,
    DescribeStep,
    describe_image,
    is_image,
)
from glados.tasks.protocols import Describer


@click.command("describe")
@paths_argument
@click.option(
    "-i",
    "--instructions",
    default=None,
    help="extra instructions, e.g. 'in Spanish' or 'one sentence'",
)
@click.option(
    "-w",
    "--write",
    is_flag=True,
    default=False,
    help="write NAME.description.txt instead of printing (implied by -o)",
)
@model_option
@backend_option("describe")
@common_file_options
@dry_run_option
@logging_options
@pass_glados
def cli(
    glados: Glados,
    paths: tuple[Path, ...],
    instructions: str | None,
    write: bool,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Print a description of each image in PATH... as `PATH: description`;
    with -w, write each to NAME.description.txt instead (needs a model that
    takes images)."""
    write = write or output is not None
    if not write and (overwrite or dry_run):
        raise click.UsageError("-y/--overwrite and -n/--dry-run need -w or -o")
    inputs = expand_inputs(paths, is_image)
    check_single_output(output, inputs)
    dest_fn = override_destination(output, suffix_destination(DESCRIPTION_EXTENSION))
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    prompt = glados.config().prompts.render_describe(instructions)
    describer = glados.backend("describe", Describer, backend, {"model": model})
    if write:
        job = Job(
            steps=[(DescribeStep(describer, prompt), "Describing")], dest_fn=dest_fn
        )
        run_jobs(inputs, job_action(job, overwrite), "Describing")
        return

    descriptions: list[tuple[Path, str]] = []

    def collect(image: Path, reporter: BaseProgressReporter) -> None:
        descriptions.append((image, describe_image(describer, prompt, image, reporter)))

    report = run_batch(inputs, collect, description="Describing")
    for image, description in descriptions:
        click.echo(f"{image}: {description}")
    finish_batch(report)


if __name__ == "__main__":
    cli()
