"""`oddjob img-trim` and `img-reduce` (need the `images` extra;
oddjob.lib.imgedit is imported only when they run, after -n)."""

from __future__ import annotations

import logging
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
from filejobs.inputs import expand_inputs
from filejobs.pipeline import BytesStep, Job, infix_destination
from filejobs.progress import BaseProgressReporter
from oddjob.commands.imghash import load_extra_module
from oddjob.core.cli_common import logging_options
from oddjob.lib import media

LOGGER = logging.getLogger(__name__)
# fsjanitor's threshold (the shorter side of 4K UHD).
DEFAULT_MAX_SIZE = 2160


@click.command("img-trim")
@paths_argument
@same_format_options
@dry_run_option
@logging_options
def img_trim_cmd(
    paths: tuple[Path, ...],
    output: Path | None,
    overwrite: bool,
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Crop each image in PATH... to its non-transparent pixels, writing
    NAME.cropped.<ext> (images without transparency fail). -n lists every
    candidate without opening the images, so it cannot tell which will fail."""
    inputs = expand_inputs(paths, media.is_autocrop_input)
    check_single_output(output, inputs)
    dest_fn = same_format_destination(
        output, in_place, infix_destination(media.CROPPED_INFIX)
    )
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    imgedit = load_extra_module("imgedit")
    job = Job(
        steps=[(BytesStep(imgedit.autocrop), "Cropping")],
        dest_fn=dest_fn,
        keep_times=keep_mtime,
    )
    run_jobs(inputs, job_action(job, overwrite or in_place), "Cropping")


@click.command("img-reduce")
@paths_argument
@click.option(
    "--max-size",
    type=click.IntRange(min=1),
    default=DEFAULT_MAX_SIZE,
    show_default=True,
    help="longest side in pixels",
)
@same_format_options
@dry_run_option
@logging_options
def img_reduce_cmd(
    paths: tuple[Path, ...],
    max_size: int,
    output: Path | None,
    overwrite: bool,
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Downscale each image in PATH... whose longest side exceeds --max-size,
    writing NAME.reduced.<ext> in the same format (EXIF and ICC profile
    kept). Images that already fit are skipped. -n lists every candidate without
    opening the images, so it cannot tell which will be skipped."""
    inputs = expand_inputs(paths, media.is_img_reduce_input)
    check_single_output(output, inputs)
    dest_fn = same_format_destination(
        output, in_place, infix_destination(media.REDUCED_INFIX)
    )
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    imgedit = load_extra_module("imgedit")

    def shrink(content: bytes) -> bytes:
        return imgedit.reduce(content, max_size)

    job = Job(
        steps=[(BytesStep(shrink), "Reducing")],
        dest_fn=dest_fn,
        keep_times=keep_mtime,
    )

    def reduce_one(input_path: Path, reporter: BaseProgressReporter) -> Path | None:
        if not imgedit.needs_reduction(input_path, max_size):
            LOGGER.info("%s: fits in %d px, skipped", input_path, max_size)
            return None
        return job.run(input_path, reporter, overwrite=overwrite or in_place)

    run_jobs(inputs, reduce_one, "Reducing")
