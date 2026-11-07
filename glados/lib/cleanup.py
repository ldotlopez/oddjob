"""fs-cleanup: remove files and directories other operating systems leave
behind, and optionally normalize permissions (files 644, directories 755).

The plan walks the trees itself instead of using filejobs.inputs, since
both actions apply to directories too. Junk directories are not descended
into, and nothing is followed through a symlink.
"""

from __future__ import annotations

import shutil
import stat
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# Exact names, matched case-sensitively (macOS, KDE).
JUNK_NAMES = frozenset(
    {
        ".DS_Store",  # macOS Finder view settings
        "Icon\r",  # macOS custom folder icon
        ".directory",  # KDE Dolphin view settings
    }
)
# Matched case-insensitively: Windows names come in any case.
JUNK_NAMES_ANY_CASE = frozenset({"thumbs.db", "ehthumbs.db", "desktop.ini"})
JUNK_DIRECTORIES = frozenset(
    {
        ".Spotlight-V100",
        ".Trashes",
        ".fseventsd",
        ".TemporaryItems",
        ".AppleDouble",
        "$RECYCLE.BIN",
    }
)
# Freedesktop trash on removable media: .Trash-<uid>.
TRASH_PREFIX = ".Trash-"
# AppleDouble resource forks: ._NAME next to NAME.
APPLE_DOUBLE_PREFIX = "._"

FILE_MODE = 0o644
DIRECTORY_MODE = 0o755


def is_junk_directory(path: Path) -> bool:
    name = path.name
    return name in JUNK_DIRECTORIES or (
        name.startswith(TRASH_PREFIX) and name.removeprefix(TRASH_PREFIX).isdigit()
    )


def is_junk_file(path: Path) -> bool:
    """A known junk name, or an AppleDouble `._NAME` whose NAME exists."""
    name = path.name
    if name in JUNK_NAMES or name.lower() in JUNK_NAMES_ANY_CASE:
        return True
    if name.startswith(APPLE_DOUBLE_PREFIX) and len(name) > len(APPLE_DOUBLE_PREFIX):
        return path.with_name(name.removeprefix(APPLE_DOUBLE_PREFIX)).exists()
    return False


@dataclass(frozen=True, slots=True)
class Removal:
    path: Path
    directory: bool

    def describe(self) -> str:
        return f"rm -r {self.path}" if self.directory else f"rm {self.path}"

    def apply(self) -> None:
        if self.directory:
            shutil.rmtree(self.path)
        else:
            self.path.unlink()


@dataclass(frozen=True, slots=True)
class Chmod:
    path: Path
    mode: int

    def describe(self) -> str:
        return f"chmod {self.mode:o} {self.path}"

    def apply(self) -> None:
        self.path.chmod(self.mode)


type CleanupAction = Removal | Chmod


def _entries(root: Path) -> Iterator[Path]:
    """`root` and, for a directory, everything below it, top-down, sorted;
    junk directories are yielded but not descended into."""
    yield root
    if root.is_symlink() or not root.is_dir() or is_junk_directory(root):
        return
    for directory, dirnames, filenames in root.walk():
        dirnames.sort()
        for name in sorted([*dirnames, *filenames]):
            yield directory / name
        dirnames[:] = [
            name
            for name in dirnames
            if not is_junk_directory(directory / name)
            and not (directory / name).is_symlink()
        ]


def plan_entry(path: Path, fix_permissions: bool) -> CleanupAction | None:
    """What to do with one entry: remove it if it is junk, else (with
    `fix_permissions`) chmod it if its mode differs. Symlinks are left alone."""
    if path.is_symlink():
        return None
    if path.is_dir():
        if is_junk_directory(path):
            return Removal(path=path, directory=True)
        target = DIRECTORY_MODE
    else:
        if is_junk_file(path):
            return Removal(path=path, directory=False)
        target = FILE_MODE
    if fix_permissions and stat.S_IMODE(path.stat().st_mode) != target:
        return Chmod(path=path, mode=target)
    return None


def plan_cleanup(roots: Iterable[Path], fix_permissions: bool) -> list[CleanupAction]:
    """Every action for `roots`, in walk order, each entry once."""
    seen: set[Path] = set()
    planned: list[CleanupAction] = []
    for root in roots:
        for entry in _entries(root):
            key = entry.absolute()
            if key in seen:
                continue
            seen.add(key)
            if (action := plan_entry(entry, fix_permissions)) is not None:
                planned.append(action)
    return planned
