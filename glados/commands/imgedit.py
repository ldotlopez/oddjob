"""`glados autocrop` and `img-reduce` (need the `images` extra;
glados.lib.imgedit is imported only when they run, after -n)."""

from __future__ import annotations

import logging
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
from filejobs.progress import BaseProgressReporter
from glados.commands.imghash import load_extra_module
from glados.core.cli_common import logging_options
from glados.lib import media

LOGGER = logging.getLogger(__name__)
# fsjanitor's threshold (the shorter side of 4K UHD).
DEFAULT_MAX_SIZE = 2160


@click.command("autocrop")
@paths_argument
@common_file_options
@dry_run_option
@logging_options
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


def same_path(input_path: Path) -> Path:
    """--in-place: the result replaces the input."""
    return input_path


@click.command("img-reduce")
@paths_argument
@click.option(
    "--max-size",
    type=click.IntRange(min=1),
    default=DEFAULT_MAX_SIZE,
    show_default=True,
    help="longest side in pixels",
)
@click.option(
    "--in-place",
    is_flag=True,
    help="replace each image atomically instead of writing NAME.reduced.<ext>",
)
@common_file_options
@dry_run_option
@logging_options
def img_reduce_cmd(
    paths: tuple[Path, ...],
    max_size: int,
    in_place: bool,
    output: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Downscale each image in PATH... whose longest side exceeds --max-size,
    writing NAME.reduced.<ext> in the same format (EXIF and ICC profile
    kept). Images that already fit are skipped; -n lists every candidate."""
    if in_place and output is not None:
        raise click.UsageError("--in-place and -o/--output are mutually exclusive")
    inputs = expand_inputs(paths, media.is_img_reduce_input)
    check_single_output(output, inputs)
    dest_fn = (
        same_path
        if in_place
        else override_destination(output, infix_destination(media.REDUCED_INFIX))
    )
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    imgedit = load_extra_module("imgedit")

    def shrink(content: bytes) -> bytes:
        return imgedit.reduce(content, max_size)

    job = Job(steps=[(BytesStep(shrink), "Reducing")], dest_fn=dest_fn)

    def reduce_one(input_path: Path, reporter: BaseProgressReporter) -> Path | None:
        if not imgedit.needs_reduction(input_path, max_size):
            LOGGER.info("%s: fits in %d px, skipped", input_path, max_size)
            return None
        return job.run(input_path, reporter, overwrite=overwrite or in_place)

    run_jobs(inputs, reduce_one, "Reducing")
