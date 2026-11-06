"""img-caption: write each image's NAME.description.txt sidecar (as
`glados describe` writes them) into the image's own metadata."""

from __future__ import annotations

import shutil
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from filejobs.pipeline import temp_output_path
from filejobs.progress import ProgressEvent, ProgressStream

DESCRIPTION_SUFFIX = ".description.txt"


class DescriptionWriter(Protocol):
    def set_description(self, path: Path, text: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Caption:
    image: Path
    sidecar: Path

    def describe(self) -> str:
        return f"caption {self.image} from {self.sidecar}"

    def text(self) -> str:
        """The sidecar's text. ValueError if it is empty: exiftool would
        delete the tags instead of setting them."""
        text = self.sidecar.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"empty description: {self.sidecar}")
        return text


def description_sidecar(image: Path) -> Path:
    return image.with_suffix(DESCRIPTION_SUFFIX)


def plan_captions(images: Sequence[Path], explicit: Collection[Path]) -> list[Caption]:
    """One Caption per image with a sidecar. An image named explicitly is
    planned even without one, so its missing sidecar fails as an input
    instead of being skipped like the images found in directories."""
    return [
        Caption(image=image, sidecar=description_sidecar(image))
        for image in images
        if image in explicit or description_sidecar(image).is_file()
    ]


class CaptionStep:
    """A copy of the input image with `text` as its description, keeping the
    input's timestamps. Satisfies ProgressStep[Path]."""

    def __init__(self, writer: DescriptionWriter, text: str) -> None:
        self.writer = writer
        self.text = text

    def run(self, input_path: Path) -> ProgressStream[Path]:
        produced = temp_output_path("multitool-caption-", input_path.suffix)
        try:
            shutil.copy2(input_path, produced)
            self.writer.set_description(produced, self.text)
            shutil.copystat(input_path, produced)
        except BaseException:
            produced.unlink(missing_ok=True)
            raise
        yield ProgressEvent(completed=1, total=1, done=True, result=produced)
