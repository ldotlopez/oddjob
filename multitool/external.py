"""Adapters for the external programs multitool runs: ImageMagick, exiftool
and arbitrary user commands. ffmpeg goes through filejobs.runners."""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def _run_tool(cmd: Sequence[str]) -> None:
    LOGGER.debug("running: %s", shlex.join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit status {proc.returncode}"
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {detail}")


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
    """Copies metadata between files with `exiftool`."""

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


def run_command_with_paths(command: Sequence[str], paths: Sequence[Path]) -> None:
    """Run a user command with `paths` appended as arguments."""
    _run_tool([*command, *(str(path) for path in paths)])
