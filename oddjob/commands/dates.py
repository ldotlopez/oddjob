"""`oddjob date-copy`: read every date first, then apply the changes."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import rich_click as click

from filejobs.batch import BatchReport, run_batch
from filejobs.cli_options import (
    dry_run_option,
    finish_batch,
    in_place_option,
    keep_mtime_option,
    overwrite_option,
    paths_argument,
    run_jobs,
)
from filejobs.inputs import expand_inputs
from filejobs.pipeline import Job
from filejobs.progress import BaseProgressReporter
from oddjob.core.cli_common import logging_options
from oddjob.lib import dates, renamers
from oddjob.lib.external import ExifTool
from oddjob.lib.shotwell import ShotwellLibrary

SOURCES = click.Choice([place.value for place in dates.Place])
TARGETS = click.Choice([place.value for place in dates.TARGETS])


def default_shotwell_db() -> Path:
    """Shotwell's own library: ~/.local/share/shotwell/data/photo.db."""
    return Path(platformdirs.user_data_dir("shotwell")) / "data" / "photo.db"


def build_exiftool() -> ExifTool:
    try:
        return ExifTool()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


def open_shotwell(database: Path) -> ShotwellLibrary:
    """The library, closed when the command ends."""
    try:
        library = ShotwellLibrary(database)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    click.get_current_context().call_on_close(library.close)
    return library


def build_source(
    place: dates.Place,
    name_format: str,
    shotwell_db: Path | None,
    exiftool: ExifTool | None,
) -> dates.DateSource:
    """The date source --from names, with what it needs."""
    match place:
        case dates.Place.MTIME:
            return dates.MtimeDates()
        case dates.Place.NAME:
            try:
                return dates.NameDates(name_format)
            except ValueError as exc:
                raise click.BadParameter(str(exc), param_hint="--name-format") from exc
        case dates.Place.EXIF:
            return dates.ExifDates(exiftool or build_exiftool())
        case dates.Place.SHOTWELL:
            return dates.ShotwellDates(
                open_shotwell(shotwell_db or default_shotwell_db())
            )


@click.command("date-copy")
@paths_argument
@click.option("--from", "source", type=SOURCES, required=True, help="read the date")
@click.option("--to", "target", type=TARGETS, required=True, help="write the date")
@click.option(
    "--name-format",
    default=dates.DEFAULT_NAME_FORMAT,
    show_default=True,
    help="where the date is in a name, for --from name (%Y %y %m %d %H %M %S)",
)
@click.option(
    "--shotwell-db",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Shotwell library for --from shotwell"
    " (default: ~/.local/share/shotwell/data/photo.db)",
)
@click.option(
    "--mtime-fallback",
    is_flag=True,
    help="use the modification time when the source has no date",
)
@overwrite_option
@in_place_option
@keep_mtime_option
@dry_run_option
@logging_options
def date_copy_cmd(
    paths: tuple[Path, ...],
    source: str,
    target: str,
    name_format: str,
    shotwell_db: Path | None,
    mtime_fallback: bool,
    overwrite: bool,
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Copy each image's or video's date in PATH... from its EXIF/QuickTime
    metadata, modification time or name (or the time a Shotwell library
    recorded) to another of them. --to name renames to
    'YYYY-mm-dd HH.MM.SS <crc32>.<ext>'; --to exif writes NAME.dated.<ext>
    (--in-place: replace the file). -n reads the dates (exiftool for --from
    exif) and prints the changes."""
    source_place, target_place = dates.Place(source), dates.Place(target)
    if source_place is target_place:
        raise click.UsageError("--from and --to must differ")
    to_exif = target_place is dates.Place.EXIF
    if (in_place or keep_mtime) and not to_exif:
        raise click.UsageError("--in-place and --keep-mtime need --to exif")
    exif_dest_fn = (lambda path: path) if in_place else dates.dated_copy

    # -n reads dates but writes nothing: exiftool only to read from it.
    needs_exiftool = source_place is dates.Place.EXIF or (to_exif and not dry_run)
    exiftool = build_exiftool() if needs_exiftool else None
    reader = build_source(source_place, name_format, shotwell_db, exiftool)
    if mtime_fallback:
        reader = dates.MtimeFallback(reader)
    planned: list[dates.DateChange] = []

    def plan(path: Path, _reporter: BaseProgressReporter) -> None:
        change = dates.plan_change(
            path, reader.read(path), target_place, exif_dest_fn=exif_dest_fn
        )
        if change is not None:
            planned.append(change)

    accepts = dates.is_exif_input if to_exif else dates.is_input
    reading = run_batch(
        expand_inputs(paths, accepts), plan, description="Reading dates"
    )
    if dry_run:
        for change in planned:
            click.echo(change.describe())
        finish_batch(reading)
        return

    if not planned:
        finish_batch(reading)
        return

    # Each file once: the ones read fine are counted by the apply batch.
    read_failures = BatchReport(failures=reading.failures)
    if to_exif:
        if exiftool is None:
            raise click.ClickException("writing EXIF dates needs exiftool")
        writer = exiftool
        exif_changes = [c for c in planned if isinstance(c, dates.SetExifDate)]

        def write(change: dates.SetExifDate, reporter: BaseProgressReporter) -> Path:
            job = Job(
                steps=[(dates.WriteTagsStep(writer, change.tags()), "Dating")],
                dest_fn=lambda _path: change.dest,
                keep_times=keep_mtime,
            )
            return job.run(change.path, reporter, overwrite=overwrite or in_place)

        run_jobs(
            exif_changes,
            write,
            "Dating",
            label=lambda change: str(change.path),
            prior=[read_failures],
        )
        return

    in_place_changes = [c for c in planned if not isinstance(c, dates.SetExifDate)]

    def apply(
        change: renamers.Rename | dates.SetMtime, _reporter: BaseProgressReporter
    ) -> None:
        dates.apply_change(change, overwrite)

    applying = run_batch(
        in_place_changes,
        apply,
        description="Dating",
        label=lambda change: change.describe(),
    )
    finish_batch(read_failures, applying)
