"""Keys for the one user cache every glados command shares.

Each command keys its entries `<tool>/<digest>`, so the commands cannot
collide in the shared store, and digests hold no path: the cache cannot be
used to find out which files were processed. The store itself (a
foundation.cache.Cache, opened by glados/core/cache.py) is what commands
receive as a `ByteStore`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class ByteStore(Protocol):
    """A foundation.cache.Cache: get raises CacheMissError on a miss."""

    def get(self, key: str) -> bytes: ...

    def set(self, key: str, value: bytes) -> None: ...


def file_sha256(path: Path) -> str:
    """The hex SHA-256 of the content of `path`."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cache_key(tool: str, *parts: str) -> str:
    """`<tool>/<SHA-256 of parts>`. Start `parts` with a version of the cached
    value's layout, so that changing the layout turns old entries into
    misses."""
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"{tool}/{digest}"
