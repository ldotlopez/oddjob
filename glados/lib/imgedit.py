"""Image edits on encoded bytes: autocrop, reduce.

Needs the `multitool` extra (Pillow, pillow-heif).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pillow_heif
from PIL import Image

# Metadata carried from the input to the edited image, when present.
KEPT_INFO = ("exif", "icc_profile")
# Lossy formats are saved with this quality instead of Pillow's default (75).
LOSSY_FORMATS = frozenset({"JPEG", "WEBP", "HEIF"})
LOSSY_QUALITY = 90


def has_transparency(image: Image.Image) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


def _encode(edited: Image.Image, original: Image.Image) -> bytes:
    """`edited` in `original`'s format, with its EXIF and ICC profile."""
    params: dict[str, Any] = {
        key: original.info[key] for key in KEPT_INFO if key in original.info
    }
    if original.format in LOSSY_FORMATS:
        params["quality"] = LOSSY_QUALITY
    output = BytesIO()
    edited.save(output, format=original.format, **params)
    return output.getvalue()


def autocrop(content: bytes) -> bytes:
    """Crop the image to the bounding box of its non-transparent pixels,
    keeping its format, EXIF and ICC profile."""
    pillow_heif.register_heif_opener()
    with Image.open(BytesIO(content)) as image:
        if not has_transparency(image):
            raise ValueError("image has no transparency to crop to")
        bbox = image.convert("RGBA").getchannel("A").getbbox()
        if bbox is None:
            raise ValueError("image is fully transparent")
        return _encode(image.crop(bbox), image)


def reduced_size(size: tuple[int, int], max_size: int) -> tuple[int, int] | None:
    """`size` scaled so its longer side is `max_size`, keeping the aspect
    ratio; None if it already fits."""
    width, height = size
    longest = max(width, height)
    if longest <= max_size:
        return None
    scale = max_size / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def needs_reduction(path: Path, max_size: int) -> bool:
    """Whether the image at `path` is larger than `max_size` on its longer
    side (reads only the header)."""
    pillow_heif.register_heif_opener()
    with Image.open(path) as image:
        return reduced_size(image.size, max_size) is not None


def reduce(content: bytes, max_size: int) -> bytes:
    """Downscale the image so its longer side is `max_size` pixels, keeping
    its format, EXIF and ICC profile. Animated images are refused."""
    pillow_heif.register_heif_opener()
    with Image.open(BytesIO(content)) as image:
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("animated images are not supported")
        size = reduced_size(image.size, max_size)
        if size is None:
            raise ValueError(f"image already fits in {max_size} px")
        return _encode(image.resize(size, Image.Resampling.LANCZOS), image)
