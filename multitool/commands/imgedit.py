"""`multitool autocrop` (needs the `multitool` extra; multitool.imgedit is
imported only when it runs, after -n)."""

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
from filejobs.pipeline import BytesStep, Job, infix_destination, override_destination
from multitool import media
from multitool.commands.imghash import load_extra_module


@click.command("autocrop")
@paths_argument
@common_file_options
@dry_run_option
def autocrop_cmd(
    paths: tuple[Path, ...], output: Path | None, overwrite: bool, dry_run: bool
) -> None:
    """Crop each image in PATH... to its non-transparent pixels, writing
    NAME.cropped.<ext> (images without transparency fail)."""
    inputs = expand_inputs(paths, media.is_autocrop_input)
    check_single_output(output, inputs)
    dest_fn = override_destination(output, infix_destination(media.CROPPED_INFIX))
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    imgedit = load_extra_module("imgedit")
    job = Job(steps=[(BytesStep(imgedit.autocrop), "Cropping")], dest_fn=dest_fn)
    run_jobs(inputs, job_action(job, overwrite), "Cropping")
