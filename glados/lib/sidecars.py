"""Sidecar groups: files in one directory that share a name and differ only
in extension (IMG_1.jpg, IMG_1.mp4, IMG_1.xmp)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SidecarGroup:
    base: Path  # directory / stem
    files: tuple[Path, ...]


def extension_of(path: Path, case_sensitive: bool = False) -> str:
    extension = path.suffix.lstrip(".")
    return extension if case_sensitive else extension.lower()


def group_sidecars(
    files: Iterable[Path], include_singles: bool = False
) -> list[SidecarGroup]:
    """Group files by directory and stem, in order of first appearance."""
    by_base: dict[Path, list[Path]] = {}
    for file in files:
        by_base.setdefault(file.parent / file.stem, []).append(file)
    return [
        SidecarGroup(base=base, files=tuple(sorted(members)))
        for base, members in by_base.items()
        if include_singles or len(members) > 1
    ]


def with_extensions(
    groups: Iterable[SidecarGroup],
    extensions: Iterable[str],
    case_sensitive: bool = False,
) -> list[SidecarGroup]:
    """Groups having every one of `extensions`, reduced to those files."""
    wanted = {
        extension.lstrip(".") if case_sensitive else extension.lstrip(".").lower()
        for extension in extensions
    }
    matching: list[SidecarGroup] = []
    for group in groups:
        kept = tuple(
            file for file in group.files if extension_of(file, case_sensitive) in wanted
        )
        if {extension_of(file, case_sensitive) for file in kept} >= wanted:
            matching.append(SidecarGroup(base=group.base, files=kept))
    return matching


def sidecars_of(file: Path, siblings: Iterable[Path]) -> SidecarGroup | None:
    """The group `file` belongs to among `siblings`, or None if alone."""
    base = file.parent / file.stem
    for group in group_sidecars(siblings):
        if group.base == base:
            return group
    return None
