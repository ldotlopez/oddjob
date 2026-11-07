"""Renames: hash-rename names each file after a digest of its content,
fix-extensions normalizes extensions."""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from filejobs.pipeline import move_to_destination

CHUNK_SIZE = 1024 * 1024
DEFAULT_ALGORITHM = "crc32"
# Applied after lowercasing; keys and values without the dot.
EXTENSION_FIXES = {"jpeg": "jpg", "mpeg": "mpg", "tif": "tiff"}


def digest_algorithms() -> list[str]:
    """crc32 plus hashlib's fixed-length algorithms (no shake_*)."""
    fixed = {
        name for name in hashlib.algorithms_available if not name.startswith("shake")
    }
    return sorted(fixed | {DEFAULT_ALGORITHM})


def _crc32(stream: BinaryIO) -> str:
    value = 0
    while chunk := stream.read(CHUNK_SIZE):
        value = zlib.crc32(chunk, value)
    return f"{value:08x}"


def file_digest(path: Path, algorithm: str) -> str:
    with path.open("rb") as stream:
        if algorithm == "crc32":
            return _crc32(stream)
        return hashlib.file_digest(stream, algorithm).hexdigest()


@dataclass(frozen=True, slots=True)
class Rename:
    source: Path
    destination: Path

    def describe(self) -> str:
        return f"mv {self.source} {self.destination}"


def plan_rename(source: Path, digest: str) -> Rename | None:
    """The rename to `<digest><suffix>`, or None if already named so."""
    destination = source.with_name(f"{digest}{source.suffix}")
    if destination == source:
        return None
    return Rename(source=source, destination=destination)


def fixed_extension(source: Path) -> Path:
    """`source` with its extension lowercased, then mapped through
    EXTENSION_FIXES (`IMG.JPEG` -> `IMG.jpg`). No extension: unchanged."""
    if not source.suffix:
        return source
    extension = source.suffix.removeprefix(".").lower()
    return source.with_suffix(f".{EXTENSION_FIXES.get(extension, extension)}")


def plan_extension_fix(source: Path) -> Rename | None:
    """The rename to the fixed extension, or None if it is already fixed."""
    destination = fixed_extension(source)
    if destination == source:
        return None
    return Rename(source=source, destination=destination)


def apply_rename(rename: Rename, overwrite: bool) -> None:
    move_to_destination(rename.source, rename.destination, overwrite)
