"""hash-rename: name each file after a digest of its content."""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from filejobs.pipeline import move_to_destination

CHUNK_SIZE = 1024 * 1024
DEFAULT_ALGORITHM = "crc32"


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


def apply_rename(rename: Rename, overwrite: bool) -> None:
    move_to_destination(rename.source, rename.destination, overwrite)
