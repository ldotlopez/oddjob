"""Average hashes of images and near-duplicate groups.

Needs the `multitool` extra (Pillow, pillow-heif).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pillow_heif
from foundation.cache import Cache, CacheMissError
from PIL import Image

DEFAULT_HASH_SIZE = 16  # 16x16 = 256-bit hash
DEFAULT_MAX_DISTANCE = 8  # bits that may differ between duplicates

# How long a cached hash stays valid; keys change with the file anyway.
CACHE_EXPIRATION = 30 * 24 * 60 * 60


def average_hash(image: Image.Image, size: int) -> str:
    """size x size grayscale thumbnail; one bit per pixel brighter than the
    mean, as hex."""
    if size < 2:
        raise ValueError(f"hash size must be at least 2: {size}")
    thumbnail = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = thumbnail.tobytes()
    mean = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | (pixel > mean)
    return f"{value:0{(size * size + 3) // 4}x}"


def hamming_distance(first: str, second: str) -> int:
    return (int(first, 16) ^ int(second, 16)).bit_count()


def duplicate_groups(
    hashes: Sequence[tuple[Path, str]], max_distance: int
) -> list[list[Path]]:
    """Connected components of images whose hashes differ in at most
    `max_distance` bits; only groups of two or more."""
    by_hash: dict[str, list[Path]] = {}
    for path, image_hash in hashes:
        by_hash.setdefault(image_hash, []).append(path)

    unique = list(by_hash)
    parent = list(range(len(unique)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first in range(len(unique)):
        for second in range(first + 1, len(unique)):
            if hamming_distance(unique[first], unique[second]) <= max_distance:
                parent[root(second)] = root(first)

    components: dict[int, list[Path]] = {}
    for index, image_hash in enumerate(unique):
        components.setdefault(root(index), []).extend(by_hash[image_hash])
    groups = [sorted(paths) for paths in components.values() if len(paths) > 1]
    return sorted(groups)


class ImageHasher:
    """Average hashes of image files, cached by path, size and mtime."""

    def __init__(self, size: int, cache: Cache | None) -> None:
        pillow_heif.register_heif_opener()
        self.size = size
        self.cache = cache

    def _key(self, path: Path) -> str:
        stat = path.stat()
        return f"ahash{self.size}:{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"

    def hash(self, path: Path) -> str:
        if self.cache is None:
            return self._compute(path)
        key = self._key(path)
        try:
            return self.cache.get(key).decode("ascii")
        except CacheMissError:
            image_hash = self._compute(path)
            self.cache.set(key, image_hash.encode("ascii"))
            return image_hash

    def _compute(self, path: Path) -> str:
        with Image.open(path) as image:
            return average_hash(image, self.size)
