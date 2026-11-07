"""Samsung-style motion photos: a JPEG followed by `MotionPhoto_Data` and an
MP4 video, in one .jpg file.

The marker string can occur more than once (Samsung's trailer index names
it again after the video), so the video marker is the first one followed
by an MP4 `ftyp` box.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from glados.lib.media import JPEG_EXTENSIONS, MP4_EXTENSION
from glados.lib.sidecars import SidecarGroup

MARKER = b"MotionPhoto_Data"


def is_mp4(content: bytes, offset: int = 0) -> bool:
    """Whether an MP4 (ISO BMFF) file starts at `offset`."""
    return content[offset + 4 : offset + 8] == b"ftyp"


def _video_marker_index(content: bytes) -> int | None:
    index = content.find(MARKER)
    while index >= 0:
        if is_mp4(content, index + len(MARKER)):
            return index
        index = content.find(MARKER, index + 1)
    return None


@dataclass(frozen=True, slots=True)
class MotionPhoto:
    image: bytes
    video: bytes | None

    @classmethod
    def parse(cls, content: bytes) -> Self:
        index = _video_marker_index(content)
        if index is None:
            return cls(image=content, video=None)
        return cls(image=content[:index], video=content[index + len(MARKER) :])

    def to_bytes(self) -> bytes:
        if self.video is None:
            return self.image
        return self.image + MARKER + self.video


def join(image: bytes, video: bytes) -> bytes:
    """A motion photo from a still JPEG and an MP4 video."""
    if MotionPhoto.parse(image).video is not None:
        raise ValueError("the image is already a motion photo")
    if not is_mp4(video):
        raise ValueError("the video is not an MP4 file")
    return MotionPhoto(image=image, video=video).to_bytes()


def split(content: bytes) -> tuple[bytes, bytes]:
    """The still image and the video of a motion photo."""
    photo = MotionPhoto.parse(content)
    if photo.video is None:
        raise ValueError("not a motion photo")
    return photo.image, photo.video


def strip(content: bytes) -> bytes:
    """The still image of a motion photo, without the video."""
    return split(content)[0]


@dataclass(frozen=True, slots=True)
class Merge:
    image: Path
    video: Path
    remove_video: bool

    def describe(self) -> str:
        action = f"merge {self.video} into {self.image}"
        return f"{action}, then remove {self.video}" if self.remove_video else action


def plan_merges(groups: Iterable[SidecarGroup], remove_video: bool) -> list[Merge]:
    """One merge per sidecar group with exactly one JPEG and one MP4."""
    merges: list[Merge] = []
    for group in groups:
        images = [f for f in group.files if f.suffix.lower() in JPEG_EXTENSIONS]
        videos = [f for f in group.files if f.suffix.lower() == MP4_EXTENSION]
        if len(images) == 1 and len(videos) == 1:
            merges.append(
                Merge(image=images[0], video=videos[0], remove_video=remove_video)
            )
    return merges
