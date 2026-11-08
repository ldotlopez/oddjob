"""img-embed-description: write each image's NAME.description.txt sidecar (as
`oddjob describe` writes them, and generates it when missing) into the image's
own metadata."""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from filejobs.pipeline import DestinationFn, temp_output_path
from filejobs.progress import ProgressEvent, ProgressStream

DESCRIPTION_SUFFIX = ".description.txt"


class DescriptionWriter(Protocol):
    def set_description(self, path: Path, text: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Caption:
    """An image to caption from `sidecar`, which `oddjob describe` writes
    first when `generate` is set; the captioned copy lands at `dest` (the
    image itself when it is replaced)."""

    image: Path
    dest: Path
    sidecar: Path
    generate: bool = False

    def describe(self) -> str:
        image, sidecar = shlex.quote(str(self.image)), shlex.quote(str(self.sidecar))
        landing = (
            "" if self.dest == self.image else f" -> {shlex.quote(str(self.dest))}"
        )
        if self.generate:
            return f"describe {image} into {sidecar}, then embed it{landing}"
        return f"embed {sidecar} into {image}{landing}"

    def text(self) -> str:
        """The sidecar's text. ValueError if it is empty: exiftool would
        delete the tags instead of setting them."""
        text = self.sidecar.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"empty description: {self.sidecar}")
        return text


def description_sidecar(image: Path) -> Path:
    return image.with_suffix(DESCRIPTION_SUFFIX)


def plan_captions(
    images: Sequence[Path], *, redescribe: bool, dest_fn: DestinationFn
) -> list[Caption]:
    """One Caption per image, landing at `dest_fn(image)`. Its description is
    generated when it has no sidecar yet, or always with `redescribe`."""
    return [
        Caption(
            image=image,
            dest=dest_fn(image),
            sidecar=description_sidecar(image),
            generate=redescribe or not description_sidecar(image).is_file(),
        )
        for image in images
    ]


class CaptionStep:
    """A copy of the input image with `text` as its description. Satisfies
    ProgressStep[Path]."""

    def __init__(self, writer: DescriptionWriter, text: str) -> None:
        self.writer = writer
        self.text = text

    def run(self, input_path: Path) -> ProgressStream[Path]:
        produced = temp_output_path("oddjob-caption-", input_path.suffix)
        try:
            shutil.copyfile(input_path, produced)
            self.writer.set_description(produced, self.text)
        except BaseException:
            produced.unlink(missing_ok=True)
            raise
        yield ProgressEvent(completed=1, total=1, done=True, result=produced)
