"""Which files are images or videos, and which ones each converter takes.

Types come from the file name (stdlib `mimetypes`), never from the content.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

# Converted to JPEG by `jpgize`.
JPEG_SOURCE_EXTENSIONS = frozenset({".heic", ".heif", ".webp", ".png"})

# Video containers that mimetypes maps to a non-video type.
EXTRA_VIDEO_EXTENSIONS = frozenset({".3gp", ".mts", ".m2ts"})

JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
MP4_EXTENSION = ".mp4"


def media_type(path: Path) -> str | None:
    return mimetypes.guess_type(path.name, strict=False)[0]


def is_image(path: Path) -> bool:
    mime = media_type(path)
    return mime is not None and mime.startswith("image/")


def is_video(path: Path) -> bool:
    if path.suffix.lower() in EXTRA_VIDEO_EXTENSIONS:
        return True
    mime = media_type(path)
    return mime is not None and mime.startswith("video/")


def converts_to_jpeg(path: Path) -> bool:
    return path.suffix.lower() in JPEG_SOURCE_EXTENSIONS


def converts_to_mp4(path: Path) -> bool:
    return is_video(path) and path.suffix.lower() != MP4_EXTENSION
