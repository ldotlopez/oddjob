"""photo-lint: find problems in photos' metadata, and fix them.

Each check is a function of the tags `READ_TAGS` names (as
`ExifTool.read_dates` returns them) listed in `CHECKS` under its code.
`set-zone` fixes `no-zone`: cameras record wall-clock times without a zone,
so it takes the zone the user names and records, next to each date, the UTC
offset that zone had at that wall-clock time, in a copy of the photo
(`SetOffsetsStep`) that lands as `NAME.fixed.<ext>` or replaces it.
"""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, available_timezones

from filejobs.pipeline import temp_output_path
from filejobs.progress import ProgressEvent, ProgressStream
from oddjob.lib import dates
from oddjob.lib.external import EXIF_DATE_FORMAT

NO_ZONE = "no-zone"

# Each image date and the EXIF tag holding its UTC offset.
DATE_OFFSET_TAGS = {**dates.OFFSET_TAGS, "ModifyDate": "OffsetTime"}
READ_TAGS = (*DATE_OFFSET_TAGS, *DATE_OFFSET_TAGS.values())

type Tags = dict[str, str]


class UnknownZoneError(ValueError):
    """No time zone has that name."""


class NonexistentTimeError(ValueError):
    """A wall-clock time skipped by the zone (the hour lost when DST starts)."""


def find_zone(name: str) -> ZoneInfo:
    """The IANA time zone called `name`, ignoring case (`europe/madrid`)."""
    keys = {key.casefold(): key for key in available_timezones()}
    key = keys.get(name.casefold())
    if key is None:
        raise UnknownZoneError(f"unknown time zone: {name}")
    return ZoneInfo(key)


def wall_clock(text: str) -> datetime | None:
    """The wall-clock time of an EXIF date as `read_dates` prints it (any
    appended offset is ignored); None for an empty or zeroed date."""
    try:
        return datetime.strptime(text[:19], EXIF_DATE_FORMAT)  # noqa: DTZ007
    except ValueError:
        return None


def zone_offset(wall: datetime, zone: ZoneInfo) -> str:
    """`zone`'s UTC offset at the wall-clock time `wall`, as `+01:00`.

    In the repeated hour at the end of daylight saving the first occurrence
    is taken, as `dates.local_time` does; a time in the skipped hour raises
    NonexistentTimeError.
    """
    local = wall.replace(tzinfo=zone, fold=0)
    if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != wall:
        raise NonexistentTimeError(f"{wall} does not exist in {zone.key}")
    return local.strftime("%:z")


def lacks_zone(tags: Tags) -> bool:
    """A capture date (original or digitized) without a valid UTC offset."""
    return any(
        wall_clock(tags.get(date_tag, "")) is not None
        and dates.utc_offset(tags.get(offset_tag, "")) is None
        for date_tag, offset_tag in dates.OFFSET_TAGS.items()
    )


CHECKS: tuple[tuple[str, Callable[[Tags], bool]], ...] = ((NO_ZONE, lacks_zone),)


def find_problems(tags: Tags) -> list[str]:
    """The codes of the checks `tags` fail, in `CHECKS` order."""
    return [code for code, failing in CHECKS if failing(tags)]


@dataclass(frozen=True, slots=True)
class SetOffsets:
    path: Path
    dest: Path  # `path` itself when the photo is replaced
    offsets: tuple[tuple[str, str], ...]  # (offset tag, `+01:00`)

    def tags(self) -> Tags:
        return dict(self.offsets)

    def describe(self) -> str:
        """The exiftool call that would do it (`-o DEST` unless in place)."""
        assignments = [f"-{tag}={value}" for tag, value in self.offsets]
        output = [] if self.dest == self.path else ["-o", str(self.dest)]
        return shlex.join(["exiftool", *assignments, *output, str(self.path)])


def plan_set_zone(
    path: Path, dest: Path, tags: Tags, zone: ZoneInfo, *, replace_offsets: bool
) -> SetOffsets | None:
    """The offsets `zone` gives `path`'s dates, to land at `dest`: those
    missing, or all with `replace_offsets`; None if there is nothing to
    write. DateNotFoundError when the photo has no date."""
    offsets: list[tuple[str, str]] = []
    dated = False
    for date_tag, offset_tag in DATE_OFFSET_TAGS.items():
        wall = wall_clock(tags.get(date_tag, ""))
        if wall is None:
            continue
        dated = True
        if replace_offsets or dates.utc_offset(tags.get(offset_tag, "")) is None:
            offsets.append((offset_tag, zone_offset(wall, zone)))
    if not dated:
        raise dates.DateNotFoundError("no date in its metadata")
    return SetOffsets(path, dest, tuple(offsets)) if offsets else None


class TagWriter(Protocol):
    def write_tags(self, path: Path, values: Mapping[str, str]) -> None: ...


class SetOffsetsStep:
    """A copy of the input photo with `change`'s offsets written. Satisfies
    ProgressStep[Path]."""

    def __init__(self, writer: TagWriter, change: SetOffsets) -> None:
        self.writer = writer
        self.change = change

    def run(self, input_path: Path) -> ProgressStream[Path]:
        produced = temp_output_path("oddjob-set-zone-", input_path.suffix)
        try:
            shutil.copyfile(input_path, produced)
            self.writer.write_tags(produced, self.change.tags())
        except BaseException:
            produced.unlink(missing_ok=True)
            raise
        yield ProgressEvent(completed=1, total=1, done=True, result=produced)
