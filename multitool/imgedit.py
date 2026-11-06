"""Image edits on encoded bytes: autocrop.

Needs the `multitool` extra (Pillow, pillow-heif).
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pillow_heif
from PIL import Image

# Metadata carried from the input to the cropped image, when present.
KEPT_INFO = ("exif", "icc_profile")


def has_transparency(image: Image.Image) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


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
        kept: dict[str, Any] = {
            key: image.info[key] for key in KEPT_INFO if key in image.info
        }
        output = BytesIO()
        image.crop(bbox).save(output, format=image.format, **kept)
    return output.getvalue()
