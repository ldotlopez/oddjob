"""describe: an image -> a text description, printed or written to a
NAME.description.txt sidecar.

Unlike the other text tasks the input is an image, not text, so the backend
gets the image's path instead of its content. Printed, the reply is just
collected (describe_image); written, it lands like any text task's
(DescribeStep, filejobs.pipeline.land_text_stream).
"""

from __future__ import annotations

from pathlib import Path

from filejobs.inputs import media_type_filter
from filejobs.pipeline import consume_stream, land_text_stream
from filejobs.progress import BaseProgressReporter, ProgressStream
from glados.lib.protocols import Describer

DESCRIPTION_EXTENSION = "description.txt"

is_image = media_type_filter("image/")


def describe_image(
    describer: Describer, prompt: str, image: Path, reporter: BaseProgressReporter
) -> str:
    """The description of `image`, with its progress shown on `reporter`."""
    events = describer.describe(image, prompt=prompt)
    return consume_stream(events, reporter, f"Describing {image.name}").strip()


class DescribeStep:
    """Asks `describer` for a description of the input image and writes it
    to a temp .txt file. Satisfies ProgressStep[Path]."""

    def __init__(self, describer: Describer, prompt: str) -> None:
        self.describer = describer
        self.prompt = prompt

    def run(self, input_path: Path) -> ProgressStream[Path]:
        events = self.describer.describe(input_path, prompt=self.prompt)
        return land_text_stream(events, ".txt")
