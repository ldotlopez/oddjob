"""Describe command: print a description of each image, or with -w/--write
land it at NAME.description.txt, via a Describer backend.

The system prompt comes from `[prompts] describe` in the config, with
-i/--instructions filling its `{instructions}`; "Reply in <language>." is
appended, the language being -l/--language or else the system locale's. Any text backend whose model
takes images implements it (lib/text_backend.py). Descriptions are cached
(oddjob/lib/cache.py) by image content, prompt, backend and its options;
--no-cache skips it. Printing is a report
under run_batch; writing is a file producer (Job + run_jobs), so -o, -y and
-n apply only then. The same click.Command is the `oddjob describe`
subcommand and the standalone `describe` tool.
"""

from __future__ import annotations

import contextlib
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
from oddjob.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_session,
)
from oddjob.core.describing import describe_prompt, open_describer
from oddjob.core.session import Session
from oddjob.lib.describe import (
    DESCRIPTION_EXTENSION,
    DescribeStep,
    describe_image,
    is_image,
)


@click.command("describe")
@paths_argument
@click.option(
    "-i",
    "--instructions",
    default=None,
    help="extra instructions, e.g. 'in Spanish' or 'one sentence'",
)
@click.option(
    "-l",
    "--language",
    default=None,
    help="language of the description, e.g. 'es' or 'Brazilian Portuguese'"
    " (default: the system locale's)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="neither read nor store cached descriptions",
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
@pass_session
def describe_cmd(
    session: Session,
    paths: tuple[Path, ...],
    instructions: str | None,
    language: str | None,
    no_cache: bool,
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
    prompt = describe_prompt(session, instructions, language)
    with contextlib.ExitStack() as stack:
        describer = open_describer(
            stack, session, backend, model, use_cache=not no_cache
        )
        if write:
            job = Job(
                steps=[(DescribeStep(describer, prompt), "Describing")],
                dest_fn=dest_fn,
            )
            run_jobs(inputs, job_action(job, overwrite), "Describing")
            return

        descriptions: list[tuple[Path, str]] = []

        def collect(image: Path, reporter: BaseProgressReporter) -> None:
            descriptions.append(
                (image, describe_image(describer, prompt, image, reporter))
            )

        report = run_batch(inputs, collect, description="Describing")
    for image, description in descriptions:
        click.echo(f"{image}: {description}")
    finish_batch(report)


if __name__ == "__main__":
    describe_cmd()
