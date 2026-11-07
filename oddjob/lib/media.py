"""Which files are images or videos, and which ones each converter or edit takes.

Types come from the file name (filejobs.inputs.media_type_filter, stdlib
`mimetypes`), never from the content.
"""

from __future__ import annotations

from pathlib import Path

from filejobs.inputs import media_type_filter

# Converted to JPEG by `jpgize`.
JPEG_SOURCE_EXTENSIONS = frozenset({".heic", ".heif", ".webp", ".png"})

# Video containers that mimetypes maps to a non-video type.
EXTRA_VIDEO_EXTENSIONS = frozenset({".3gp", ".mts", ".m2ts"})

JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
MP4_EXTENSION = ".mp4"

is_image = media_type_filter("image/")
has_video_type = media_type_filter("video/")


def is_video(path: Path) -> bool:
    return path.suffix.lower() in EXTRA_VIDEO_EXTENSIONS or has_video_type(path)


def converts_to_jpeg(path: Path) -> bool:
    return path.suffix.lower() in JPEG_SOURCE_EXTENSIONS


def converts_to_mp4(path: Path) -> bool:
    return is_video(path) and path.suffix.lower() != MP4_EXTENSION


# `autocrop` writes NAME.<CROPPED_INFIX>.<ext>.
CROPPED_INFIX = "cropped"


def is_output_of(path: Path, infix: str) -> bool:
    """Whether `path` is NAME.<infix>.<ext>, an earlier output of a command
    writing through infix_destination(infix)."""
    return path.stem.endswith(f".{infix}")


def is_autocrop_input(path: Path) -> bool:
    """Images, except earlier autocrop outputs (NAME.cropped.<ext>)."""
    return is_image(path) and not is_output_of(path, CROPPED_INFIX)


# `img-reduce` writes NAME.<REDUCED_INFIX>.<ext>, in a format Pillow can
# write back.
REDUCED_INFIX = "reduced"
REDUCIBLE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif"}
)


def is_img_reduce_input(path: Path) -> bool:
    """Raster images, except earlier img-reduce outputs (NAME.reduced.<ext>)."""
    return path.suffix.lower() in REDUCIBLE_EXTENSIONS and not is_output_of(
        path, REDUCED_INFIX
    )
