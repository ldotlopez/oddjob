"""`oddjob photo-lint`: check photos' metadata and fix what the checks find."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import rich_click as click

from filejobs.batch import BatchReport, run_batch
from filejobs.cli_options import (
    check_single_output,
    dry_run_option,
    finish_batch,
    paths_argument,
    run_jobs,
    same_format_destination,
    same_format_options,
)
from filejobs.inputs import expand_inputs
from filejobs.pipeline import Job, infix_destination
from filejobs.progress import BaseProgressReporter
from oddjob.commands.dates import build_exiftool
from oddjob.core.cli_common import logging_options
from oddjob.lib import media, photolint


def parse_zone(_ctx: click.Context, _param: click.Parameter, name: str) -> ZoneInfo:
    try:
        return photolint.find_zone(name)
    except photolint.UnknownZoneError as exc:
        raise click.BadParameter(str(exc)) from exc


@click.group("photo-lint")
def photo_lint_cmd() -> None:
    """Check photos' metadata and fix the problems found."""


@photo_lint_cmd.command("check")
@paths_argument
@logging_options
def check_cmd(paths: tuple[Path, ...]) -> None:
    """Print each image in PATH... that fails a check, as 'PATH: CODE'
    (no-zone: a capture date without a UTC offset); exit 1 if there was any."""
    exiftool = build_exiftool()
    problems: list[tuple[Path, str]] = []

    def check(path: Path, _reporter: BaseProgressReporter) -> None:
        tags = exiftool.read_dates(path, photolint.READ_TAGS)
        problems.extend((path, code) for code in photolint.find_problems(tags))

    report = run_batch(
        expand_inputs(paths, media.is_image), check, description="Checking"
    )
    for path, code in problems:
        click.echo(f"{path}: {code}")
    finish_batch(report)
    if problems:
        raise click.exceptions.Exit(1)


@photo_lint_cmd.command("set-zone")
@paths_argument
@click.option(
    "--zone",
    required=True,
    callback=parse_zone,
    help="IANA time zone the EXIF dates' wall-clock times are in (Europe/Madrid)",
)
@click.option(
    "--replace-offsets", is_flag=True, help="also rewrite offsets already recorded"
)
@same_format_options
@dry_run_option
@logging_options
def set_zone_cmd(
    paths: tuple[Path, ...],
    zone: ZoneInfo,
    replace_offsets: bool,
    output: Path | None,
    overwrite: bool,
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Record, next to each EXIF date of the images in PATH..., the UTC
    offset --zone had at that wall-clock time (OffsetTimeOriginal,
    OffsetTimeDigitized, OffsetTime), writing NAME.fixed.<ext> (--in-place:
    replace the image). Dates that already have one are kept unless
    --replace-offsets; images with nothing to write are skipped. -n reads the
    dates and prints the changes."""
    inputs = expand_inputs(paths, media.is_set_zone_input)
    check_single_output(output, inputs)
    dest_fn = same_format_destination(
        output, in_place, infix_destination(media.FIXED_INFIX)
    )
    exiftool = build_exiftool()
    planned: list[photolint.SetOffsets] = []

    def plan(path: Path, _reporter: BaseProgressReporter) -> None:
        tags = exiftool.read_dates(path, photolint.READ_TAGS)
        change = photolint.plan_set_zone(
            path, dest_fn(path), tags, zone, replace_offsets=replace_offsets
        )
        if change is not None:
            planned.append(change)

    reading = run_batch(inputs, plan, description="Reading dates")
    if dry_run or not planned:
        for change in planned:
            click.echo(change.describe())
        finish_batch(reading)
        return

    def apply(change: photolint.SetOffsets, reporter: BaseProgressReporter) -> Path:
        job = Job(
            steps=[(photolint.SetOffsetsStep(exiftool, change), "Zoning")],
            dest_fn=lambda _path: change.dest,
            keep_times=keep_mtime,
        )
        return job.run(change.path, reporter, overwrite=overwrite or in_place)

    # Each file once: the ones read fine are counted by the apply batch.
    run_jobs(
        planned,
        apply,
        "Zoning",
        label=lambda change: str(change.path),
        prior=[BatchReport(failures=reading.failures)],
    )
