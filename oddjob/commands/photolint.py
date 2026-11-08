"""`oddjob photo-lint`: check photos' metadata and fix what the checks find."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import rich_click as click

from filejobs.batch import BatchReport, run_batch
from filejobs.cli_options import (
    dry_run_option,
    finish_batch,
    overwrite_option,
    paths_argument,
    require_overwrite,
)
from filejobs.inputs import expand_inputs
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
@click.option("--replace", is_flag=True, help="also rewrite offsets already recorded")
@overwrite_option
@dry_run_option
@logging_options
def set_zone_cmd(
    paths: tuple[Path, ...],
    zone: ZoneInfo,
    replace: bool,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Record, next to each EXIF date of the images in PATH..., the UTC
    offset --zone had at that wall-clock time (OffsetTimeOriginal,
    OffsetTimeDigitized, OffsetTime). Dates that already have one are kept
    unless --replace. Rewrites files in place (needs -y); -n reads the dates
    and prints the changes."""
    if not dry_run:
        require_overwrite(overwrite, "set-zone rewrites files in place")
    exiftool = build_exiftool()
    planned: list[photolint.SetOffsets] = []

    def plan(path: Path, _reporter: BaseProgressReporter) -> None:
        tags = exiftool.read_dates(path, photolint.READ_TAGS)
        change = photolint.plan_set_zone(path, tags, zone, replace=replace)
        if change is not None:
            planned.append(change)

    reading = run_batch(
        expand_inputs(paths, media.is_image), plan, description="Reading dates"
    )
    if dry_run or not planned:
        for change in planned:
            click.echo(change.describe())
        finish_batch(reading)
        return

    def apply(change: photolint.SetOffsets, _reporter: BaseProgressReporter) -> None:
        exiftool.write_tags(change.path, change.tags())

    applying = run_batch(
        planned, apply, description="Zoning", label=lambda change: change.describe()
    )
    # Each file once: the ones read fine are counted by the apply batch.
    finish_batch(BatchReport(failures=reading.failures), applying)
