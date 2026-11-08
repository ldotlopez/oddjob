"""date-copy: copy a file's date from one place to another, among its
EXIF/QuickTime metadata, its modification time and its name; a Shotwell
library can also be read as the source.

Cameras record wall-clock times without a zone; they are read with the
UTC offset the file records next to them (EXIF `OffsetTime*`, or QuickTime's
UTC), else as local time (aware datetimes in the system's zone). Writing EXIF
dates records the offset too, so the repeated hour at the end of daylight
saving stays unambiguous; they go into a copy, `NAME.dated.<ext>`
(`WriteTagsStep`), unless the file is replaced. A dated name is
`YYYY-mm-dd HH.MM.SS <crc32>.<ext>`: the checksum keeps shots taken in the
same second apart, and the extension is normalized as fix-extensions does.
"""

from __future__ import annotations

import enum
import os
import re
import shlex
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Protocol

from filejobs.pipeline import DestinationFn, infix_destination, temp_output_path
from filejobs.progress import ProgressEvent, ProgressStream
from oddjob.lib import media, renamers
from oddjob.lib.external import EXIF_DATE_FORMAT, ExifTool
from oddjob.lib.shotwell import ShotwellLibrary


class DateNotFoundError(ValueError):
    """The source has no date for a file (a ValueError, so a JOB_ERROR)."""


class Place(enum.StrEnum):
    EXIF = "exif"
    MTIME = "mtime"
    NAME = "name"
    SHOTWELL = "shotwell"  # a source only: the library is never written


TARGETS = (Place.EXIF, Place.MTIME, Place.NAME)


# Read in this order of preference: when the shot was taken, then when it
# was digitized (images) or created (QuickTime), then the media track's.
EXIF_READ_TAGS = ("DateTimeOriginal", "CreateDate", "MediaCreateDate")
# The EXIF tag holding the UTC offset of each image date.
OFFSET_TAGS = {
    "DateTimeOriginal": "OffsetTimeOriginal",
    "CreateDate": "OffsetTimeDigitized",
}
# AllDates is DateTimeOriginal, CreateDate and ModifyDate.
EXIF_IMAGE_WRITE_TAGS = ("AllDates",)
EXIF_IMAGE_OFFSET_WRITE_TAGS = (
    "OffsetTimeOriginal",
    "OffsetTimeDigitized",
    "OffsetTime",
)
EXIF_VIDEO_WRITE_TAGS = (
    "AllDates",
    "TrackCreateDate",
    "TrackModifyDate",
    "MediaCreateDate",
    "MediaModifyDate",
)

DATED_NAME_FORMAT = "%Y-%m-%d %H.%M.%S"
# Default --name-format: reads back the names date-copy writes.
DEFAULT_NAME_FORMAT = DATED_NAME_FORMAT
NAME_FIELDS = {
    "Y": r"\d{4}",
    "y": r"\d{2}",
    "m": r"\d{2}",
    "d": r"\d{2}",
    "H": r"\d{2}",
    "M": r"\d{2}",
    "S": r"\d{2}",
}
REQUIRED_NAME_FIELDS = ({"Y", "y"}, {"m"}, {"d"})


def is_input(path: Path) -> bool:
    """Images and videos: the files that carry a capture date."""
    return media.is_image(path) or media.is_video(path)


def is_exif_input(path: Path) -> bool:
    """Inputs of `--to exif`: except earlier dated copies (NAME.dated.<ext>)."""
    return is_input(path) and not media.is_output_of(path, media.DATED_INFIX)


# Where `--to exif` writes, unless it replaces the file.
dated_copy = infix_destination(media.DATED_INFIX)


def name_pattern(name_format: str) -> re.Pattern[str]:
    """A regex searching file names for `name_format`, which may use %Y %y
    %m %d %H %M %S (each once; date fields required) and %%."""
    parts: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(name_format):
        char = name_format[index]
        if char != "%":
            parts.append(re.escape(char))
            index += 1
            continue
        field = name_format[index + 1 : index + 2]
        index += 2
        if field == "%":
            parts.append("%")
        elif field in NAME_FIELDS and field not in seen:
            seen.add(field)
            parts.append(f"(?P<{field}>{NAME_FIELDS[field]})")
        else:
            raise ValueError(f"unsupported or repeated field in name format: %{field}")
    if not all(seen & required for required in REQUIRED_NAME_FIELDS):
        raise ValueError("name format needs a year (%Y or %y), %m and %d")
    return re.compile("".join(parts))


def date_from_name(name: str, pattern: re.Pattern[str]) -> datetime:
    match = pattern.search(name)
    if match is None:
        raise DateNotFoundError("name does not match the name format")
    fields = match.groupdict()
    year = fields["Y"] if fields.get("Y") else f"20{fields['y']}"
    clock = ":".join(fields.get(field) or "00" for field in ("H", "M", "S"))
    return local_time(f"{year}:{fields['m']}:{fields['d']} {clock}")


def local_time(text: str) -> datetime:
    """An EXIF_DATE_FORMAT wall-clock time, read as local time.

    A time in the repeated hour at the end of daylight saving is ambiguous
    without an offset; the first occurrence (still daylight time) is taken.
    """
    return datetime.strptime(text, EXIF_DATE_FORMAT).astimezone()


def date_from_tags(tags: dict[str, str], *, utc_based: bool = False) -> datetime | None:
    """The first valid date among EXIF_READ_TAGS (zeroed dates are unset).

    The date keeps the UTC offset its file records: the `OffsetTime*` tag of
    an EXIF date, or, when `utc_based` (QuickTime dates, read through
    exiftool's UTC conversion), the offset printed after the date. Without
    one it is read as local time.
    """
    for tag in EXIF_READ_TAGS:
        text = tags.get(tag, "")
        offset = text[19:] if utc_based else tags.get(OFFSET_TAGS.get(tag, ""), "")
        try:
            return recorded_time(text[:19], offset)
        except ValueError:
            continue
    return None


def recorded_time(text: str, offset: str) -> datetime:
    """An EXIF_DATE_FORMAT wall-clock time with a recorded UTC offset
    (`+01:00` or `+0100`); local time when `offset` is empty or invalid."""
    wall = datetime.strptime(text, EXIF_DATE_FORMAT)  # noqa: DTZ007
    zone = utc_offset(offset)
    return wall.astimezone() if zone is None else wall.replace(tzinfo=zone)


def utc_offset(offset: str) -> tzinfo | None:
    """A recorded UTC offset (`+01:00` or `+0100`); None when empty or invalid."""
    try:
        return datetime.fromisoformat(f"2000-01-01T00:00:00{offset}").tzinfo
    except ValueError:
        return None


def date_from_mtime(path: Path) -> datetime:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return mtime.astimezone().replace(microsecond=0)


def dated_name(source: Path, when: datetime, digest: str) -> Path:
    """`source` renamed to `YYYY-mm-dd HH.MM.SS <digest>.<ext>`."""
    suffix = renamers.fixed_extension(source).suffix
    return source.with_name(f"{when.strftime(DATED_NAME_FORMAT)} {digest}{suffix}")


@dataclass(frozen=True, slots=True)
class SetMtime:
    path: Path
    when: datetime

    def describe(self) -> str:
        when = f"{self.when:%Y-%m-%d %H:%M:%S}"
        return shlex.join(["touch", "-m", "-d", when, str(self.path)])


@dataclass(frozen=True, slots=True)
class SetExifDate:
    path: Path
    dest: Path  # `path` itself when the file is replaced
    when: datetime

    def tags(self) -> dict[str, str]:
        """The tags to write. A video's dates carry the offset in their value
        (QuickTime stores UTC); an image's go in the `OffsetTime*` tags,
        which also replace any stale offset."""
        wall = self.when.strftime(EXIF_DATE_FORMAT)
        offset = self.when.strftime("%:z")
        if media.is_video(self.path):
            return {tag: f"{wall}{offset}" for tag in EXIF_VIDEO_WRITE_TAGS}
        return {
            **dict.fromkeys(EXIF_IMAGE_WRITE_TAGS, wall),
            **dict.fromkeys(EXIF_IMAGE_OFFSET_WRITE_TAGS, offset),
        }

    def describe(self) -> str:
        assignments = [f"-{tag}={value}" for tag, value in self.tags().items()]
        output = [] if self.dest == self.path else ["-o", str(self.dest)]
        return shlex.join(["exiftool", *assignments, *output, str(self.path)])


type DateChange = renamers.Rename | SetMtime | SetExifDate


class DateSource(Protocol):
    def read(self, path: Path) -> datetime:
        """`path`'s date; DateNotFoundError when this source has none."""
        ...


class MtimeDates:
    def read(self, path: Path) -> datetime:
        return date_from_mtime(path)


class NameDates:
    def __init__(self, name_format: str) -> None:
        self.pattern = name_pattern(name_format)

    def read(self, path: Path) -> datetime:
        return date_from_name(path.name, self.pattern)


class ExifDates:
    def __init__(self, exiftool: ExifTool) -> None:
        self.exiftool = exiftool

    def read(self, path: Path) -> datetime:
        tags = self.exiftool.read_dates(path, (*EXIF_READ_TAGS, *OFFSET_TAGS.values()))
        when = date_from_tags(tags, utc_based=media.is_video(path))
        if when is None:
            raise DateNotFoundError("no date in its metadata")
        return when


class ShotwellDates:
    """Exposure times from a Shotwell library, matched by the file's path."""

    def __init__(self, library: ShotwellLibrary) -> None:
        self.library = library

    def read(self, path: Path) -> datetime:
        exposure = self.library.exposure_time(path)
        if exposure is None:
            raise DateNotFoundError("not in the Shotwell library, or no time there")
        return datetime.fromtimestamp(exposure, tz=UTC).astimezone()


class MtimeFallback:
    """`source`'s date, or the modification time when it has none."""

    def __init__(self, source: DateSource) -> None:
        self.source = source

    def read(self, path: Path) -> datetime:
        try:
            return self.source.read(path)
        except DateNotFoundError:
            return date_from_mtime(path)


def plan_change(
    path: Path, when: datetime, target: Place, *, exif_dest_fn: DestinationFn
) -> DateChange | None:
    """What sets `path`'s `target` to `when`; None if it already is. An EXIF
    change lands at `exif_dest_fn(path)`."""
    match target:
        case Place.NAME:
            dest = dated_name(path, when, renamers.file_digest(path, "crc32"))
            return None if dest == path else renamers.Rename(path, dest)
        case Place.MTIME:
            return None if date_from_mtime(path) == when else SetMtime(path, when)
        case Place.EXIF:
            return SetExifDate(path, exif_dest_fn(path), when)
        case Place.SHOTWELL:
            raise ValueError("the Shotwell library can only be read")


def apply_change(change: renamers.Rename | SetMtime, overwrite: bool) -> None:
    """Rename or touch a file in place; EXIF changes go through a Job with
    WriteTagsStep instead."""
    match change:
        case renamers.Rename():
            renamers.apply_rename(change, overwrite)
        case SetMtime():
            atime = change.path.stat().st_atime
            os.utime(change.path, (atime, change.when.timestamp()))


class TagWriter(Protocol):
    def write_tags(self, path: Path, values: Mapping[str, str]) -> None: ...


class WriteTagsStep:
    """A copy of the input file with `tags` written. Satisfies
    ProgressStep[Path]."""

    def __init__(self, writer: TagWriter, tags: Mapping[str, str]) -> None:
        self.writer = writer
        self.tags = tags

    def run(self, input_path: Path) -> ProgressStream[Path]:
        produced = temp_output_path("oddjob-tags-", input_path.suffix)
        try:
            shutil.copyfile(input_path, produced)
            self.writer.write_tags(produced, self.tags)
        except BaseException:
            produced.unlink(missing_ok=True)
            raise
        yield ProgressEvent(completed=1, total=1, done=True, result=produced)
