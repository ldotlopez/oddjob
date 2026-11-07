"""`multitool date-sync`: read every date first, then apply the changes."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.batch import BatchReport, run_batch
from filejobs.cli_options import (
    dry_run_option,
    finish_batch,
    overwrite_option,
    paths_argument,
)
from filejobs.inputs import expand_inputs
from filejobs.progress import BaseProgressReporter
from multitool import dates
from multitool.external import ExifTool

PLACES = click.Choice([place.value for place in dates.Place])


def build_exiftool() -> ExifTool:
    try:
        return ExifTool()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


@click.command("date-sync")
@paths_argument
@click.option("--from", "source", type=PLACES, required=True, help="read the date")
@click.option("--to", "target", type=PLACES, required=True, help="write the date")
@click.option(
    "--name-format",
    default=dates.DEFAULT_NAME_FORMAT,
    show_default=True,
    help="where the date is in a name, for --from name (%Y %y %m %d %H %M %S)",
)
@click.option(
    "--mtime-fallback",
    is_flag=True,
    help="use the modification time when the source has no date",
)
@overwrite_option
@dry_run_option
def date_sync_cmd(
    paths: tuple[Path, ...],
    source: str,
    target: str,
    name_format: str,
    mtime_fallback: bool,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Copy each image's or video's date in PATH... from its EXIF/QuickTime
    metadata, modification time or name to another of them. --to name
    renames to 'YYYY-mm-dd HH.MM.SS <crc32>.<ext>'; --to exif rewrites the
    file in place (needs -y). -n reads the dates (exiftool for --from exif)
    and prints the changes."""
    source_place, target_place = dates.Place(source), dates.Place(target)
    if source_place is target_place:
        raise click.UsageError("--from and --to must differ")
    if target_place is dates.Place.EXIF and not overwrite and not dry_run:
        raise click.UsageError("--to exif rewrites files in place: add -y")
    try:
        dates.name_pattern(name_format)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--name-format") from exc

    # -n reads dates but writes nothing: exiftool only to read from it.
    needs_exiftool = source_place is dates.Place.EXIF or (
        target_place is dates.Place.EXIF and not dry_run
    )
    exiftool = build_exiftool() if needs_exiftool else None
    reader = dates.DateReader(source_place, exiftool, name_format, mtime_fallback)
    planned: list[dates.DateChange] = []

    def plan(path: Path, _reporter: BaseProgressReporter) -> None:
        change = dates.plan_change(path, reader.read(path), target_place)
        if change is not None:
            planned.append(change)

    reading = run_batch(
        expand_inputs(paths, dates.is_input), plan, description="Reading dates"
    )
    if dry_run:
        for change in planned:
            click.echo(change.describe())
        finish_batch(reading)
        return

    if not planned:
        finish_batch(reading)
        return

    def apply(change: dates.DateChange, _reporter: BaseProgressReporter) -> None:
        dates.apply_change(change, exiftool, overwrite)

    applying = run_batch(
        planned, apply, description="Dating", label=lambda change: change.describe()
    )
    # Each file once: the ones read fine are counted by the apply batch.
    finish_batch(BatchReport(failures=reading.failures), applying)
