"""Expand command-line paths into the input files of a command.

A file argument is used as is. A directory argument is walked recursively
and contributes the files the command accepts; which files qualify is the
caller's decision (`accepts`), not this module's.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

type FileFilter = Callable[[Path], bool]


def expand_inputs(paths: Iterable[Path], accepts: FileFilter) -> list[Path]:
    """Input files in argument order, each directory's files sorted, no
    duplicates."""
    seen: set[Path] = set()
    inputs: list[Path] = []
    for path in paths:
        if path.is_dir():
            candidates = sorted(
                child for child in path.rglob("*") if child.is_file() and accepts(child)
            )
        else:
            candidates = [path]
        for candidate in candidates:
            key = candidate.resolve()
            if key not in seen:
                seen.add(key)
                inputs.append(candidate)
    return inputs


def accept_all(path: Path) -> bool:
    """Every file qualifies."""
    return True
