"""Writing results next to their destination and moving them into place."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from glados.core.pipeline import check_destination, move_to_destination


@contextmanager
def temp_sibling(destination: Path, suffix: str) -> Iterator[Path]:
    """A temp file in the destination's directory (same filesystem, so the
    final move is a rename), removed on exit unless it was moved away."""
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=".multitool-", suffix=suffix, dir=destination.parent
    )
    os.close(file_descriptor)
    produced = Path(temp_name)
    try:
        yield produced
    finally:
        produced.unlink(missing_ok=True)


def write_into_place(
    content: bytes, destination: Path, *, overwrite: bool, stat_source: Path
) -> None:
    """Write `content` to `destination` through a temp file, carrying over
    `stat_source`'s permissions and timestamps."""
    check_destination(destination, overwrite)
    with temp_sibling(destination, destination.suffix) as produced:
        produced.write_bytes(content)
        shutil.copystat(stat_source, produced)
        move_to_destination(produced, destination, overwrite)
