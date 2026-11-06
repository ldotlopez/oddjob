"""describe: an image -> a text description sidecar (NAME.description.txt).

Unlike the other text tasks the input is an image, not text, so the step
hands the backend the image's path instead of its content; the reply lands
like any text task's (filejobs.pipeline.land_text_stream).
"""

from __future__ import annotations

from pathlib import Path

from filejobs.inputs import media_type_filter
from filejobs.pipeline import land_text_stream
from filejobs.progress import ProgressStream
from glados.tasks.protocols import Describer

DESCRIPTION_EXTENSION = "description.txt"

is_image = media_type_filter("image/")


class DescribeStep:
    """Asks `describer` for a description of the input image and writes it
    to a temp .txt file. Satisfies ProgressStep[Path]."""

    def __init__(self, describer: Describer, prompt: str) -> None:
        self.describer = describer
        self.prompt = prompt

    def run(self, input_path: Path) -> ProgressStream[Path]:
        events = self.describer.describe(input_path, prompt=self.prompt)
        return land_text_stream(events, ".txt")
