"""Adapters for the external programs multitool runs: ImageMagick, exiftool
and arbitrary user commands. ffmpeg goes through filejobs.runners."""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

LOGGER = logging.getLogger(__name__)
# How exiftool reads and writes dates (EXIF's own layout).
EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


def _run_tool(cmd: Sequence[str]) -> str:
    """Run `cmd` and return its stdout; a non-zero exit is a RuntimeError."""
    LOGGER.debug("running: %s", shlex.join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit status {proc.returncode}"
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {detail}")
    return proc.stdout


def _require_binary(*candidates: str) -> str:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    raise FileNotFoundError(f"{' or '.join(candidates)} not found on PATH")


class ImageMagick:
    """Converts images with `magick` (ImageMagick 7), else `convert` (6)."""

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or _require_binary("magick", "convert")

    def to_jpeg(self, source: Path, destination: Path) -> None:
        """Write the first frame of `source`, rotated per its EXIF
        orientation, as a JPEG at `destination`."""
        _run_tool([self.binary, f"{source}[0]", "-auto-orient", str(destination)])
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError(f"{Path(self.binary).name} produced no image")


class ExifTool:
    """Copies and writes metadata with `exiftool`."""

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or _require_binary("exiftool")

    def copy_tags(self, source: Path, destination: Path) -> None:
        """Copy all tags of `source` into `destination`, translated to the
        destination format's groups (e.g. PNG text chunks to EXIF), except
        Orientation: the destination's pixels are already upright."""
        _run_tool(
            [
                self.binary,
                "-quiet",
                "-overwrite_original",
                "-tagsFromFile",
                str(source),
                "--Orientation",
                str(destination),
            ]
        )

    def set_description(self, path: Path, text: str) -> None:
        """Set XMP-dc:Description and EXIF:ImageDescription of `path` to
        `text`, in place."""
        _run_tool(
            [
                self.binary,
                "-quiet",
                "-overwrite_original",
                "-charset",
                "exif=utf8",
                f"-XMP-dc:Description={text}",
                f"-EXIF:ImageDescription={text}",
                str(path),
            ]
        )

    def read_dates(self, path: Path, tags: Sequence[str]) -> dict[str, str]:
        """The `tags` of `path` that are set, as exiftool prints them with
        EXIF_DATE_FORMAT; QuickTime dates are converted from UTC to local
        time (`-api QuickTimeUTC`)."""
        output = _run_tool(
            [
                self.binary,
                "-json",
                "-api",
                "QuickTimeUTC",
                "-d",
                EXIF_DATE_FORMAT,
                *(f"-{tag}" for tag in tags),
                str(path),
            ]
        )
        try:
            (entry,) = json.loads(output)
        except ValueError as exc:
            raise RuntimeError(f"exiftool printed no JSON object: {exc}") from exc
        return {tag: str(entry[tag]) for tag in tags if tag in entry}

    def write_dates(self, path: Path, tags: Sequence[str], value: str) -> None:
        """Set every one of `tags` of `path` to `value` (EXIF_DATE_FORMAT,
        local time) in place, keeping the file's modification time."""
        _run_tool(
            [
                self.binary,
                "-quiet",
                "-overwrite_original",
                "-preserve",
                "-api",
                "QuickTimeUTC",
                *(f"-{tag}={value}" for tag in tags),
                str(path),
            ]
        )


def run_command_with_paths(command: Sequence[str], paths: Sequence[Path]) -> None:
    """Run a user command with `paths` appended as arguments."""
    _run_tool([*command, *(str(path) for path in paths)])
