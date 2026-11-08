"""Samsung-style motion photos: a JPEG followed by `MotionPhoto_Data` and an
MP4 video, in one .jpg file.

The marker string can occur more than once (Samsung's trailer index names
it again after the video), so the video marker is the first one followed
by an MP4 `ftyp` box (`is_mp4`).
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from filejobs.pipeline import DestinationFn
from oddjob.lib.media import JPEG_EXTENSIONS, MP4_EXTENSION
from oddjob.lib.sidecars import SidecarGroup

MARKER = b"MotionPhoto_Data"


# Major brands of the MP4 family, whatever the codec inside. Other ISO BMFF
# files (QuickTime `qt  `, 3GP, HEIF, AVIF) also start with `ftyp` but are
# not MP4: Android motion photos carry an MP4 video.
MP4_BRANDS = frozenset(
    {b"isom", b"mp41", b"mp42", b"avc1", b"dash"}
    | {f"iso{version}".encode() for version in range(2, 10)}
)


def is_mp4(content: bytes, offset: int = 0) -> bool:
    """Whether an MP4 file (an `ftyp` box with an MP4 major brand) starts
    at `offset`."""
    box = content[offset + 4 : offset + 12]
    return box[:4] == b"ftyp" and box[4:] in MP4_BRANDS


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
    dest: Path  # `image` itself when it is replaced
    remove_video: bool

    def describe(self) -> str:
        video, image = shlex.quote(str(self.video)), shlex.quote(str(self.image))
        action = f"merge {video} into {image}"
        if self.dest != self.image:
            action += f" -> {shlex.quote(str(self.dest))}"
        return f"{action}, then remove {video}" if self.remove_video else action


def plan_merges(
    groups: Iterable[SidecarGroup], remove_video: bool, dest_fn: DestinationFn
) -> list[Merge]:
    """One merge per sidecar group with exactly one JPEG and one MP4, landing
    at `dest_fn(image)`."""
    merges: list[Merge] = []
    for group in groups:
        images = [f for f in group.files if f.suffix.lower() in JPEG_EXTENSIONS]
        videos = [f for f in group.files if f.suffix.lower() == MP4_EXTENSION]
        if len(images) == 1 and len(videos) == 1:
            merges.append(
                Merge(
                    image=images[0],
                    video=videos[0],
                    dest=dest_fn(images[0]),
                    remove_video=remove_video,
                )
            )
    return merges
