"""describe: an image -> a text description, printed or written to a
NAME.description.txt sidecar.

Unlike the other text tasks the input is an image, not text, so the backend
gets the image's path instead of its content. Printed, the reply is just
collected (describe_image); written, it lands like any text task's
(DescribeStep, filejobs.pipeline.land_text_stream).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundation.cache import CacheMissError

from filejobs.inputs import media_type_filter
from filejobs.pipeline import consume_stream, land_text_stream
from filejobs.progress import BaseProgressReporter, ProgressEvent, ProgressStream
from glados.lib.cache import ByteStore, cache_key, file_sha256
from glados.lib.protocols import Describer

DESCRIPTION_EXTENSION = "description.txt"
CACHE_TOOL = "describe"
# Bumped when the cached value's layout changes, so old entries are misses.
CACHE_LAYOUT_VERSION = "1"

# Backend options that do not change a description and must not end up in a key.
SECRET_OPTIONS = frozenset({"api_key"})

LOGGER = logging.getLogger(__name__)

is_image = media_type_filter("image/")


def describe_image(
    describer: Describer, prompt: str, image: Path, reporter: BaseProgressReporter
) -> str:
    """The description of `image`, with its progress shown on `reporter`."""
    events = describer.describe(image, prompt=prompt)
    return consume_stream(events, reporter, f"Describing {image.name}").strip()


@dataclass(frozen=True, slots=True)
class DescriptionSettings:
    """What changes a description besides the image and the prompt: the
    backend that makes it and the options (model, endpoint, ...) it is
    configured with."""

    backend: str
    options: Mapping[str, Any]


def description_key(image: Path, prompt: str, settings: DescriptionSettings) -> str:
    """Keyed by the image's content SHA-256, the prompt and the settings."""
    return cache_key(
        CACHE_TOOL,
        CACHE_LAYOUT_VERSION,
        file_sha256(image),
        prompt,
        settings.backend,
        json.dumps(
            {k: v for k, v in settings.options.items() if k not in SECRET_OPTIONS},
            sort_keys=True,
            default=str,
        ),
    )


class CachedDescriber:
    """A Describer that answers from the store when it can, else from the
    describer `make_describer` builds on the first miss."""

    def __init__(
        self,
        store: ByteStore,
        make_describer: Callable[[], Describer],
        settings: DescriptionSettings,
    ) -> None:
        self.store = store
        self.make_describer = make_describer
        self.settings = settings
        self._describer: Describer | None = None

    def describe(self, image: Path, *, prompt: str) -> ProgressStream[str]:
        key = description_key(image, prompt, self.settings)
        try:
            cached = self.store.get(key).decode("utf-8")
        except CacheMissError:
            pass
        except UnicodeDecodeError as exc:
            LOGGER.warning("%s: ignoring unreadable cached description: %s", image, exc)
        else:
            LOGGER.debug("%s: description from cache", image)
            yield ProgressEvent(completed=1, total=1, done=True, result=cached)
            return
        if self._describer is None:
            self._describer = self.make_describer()
        events = self._describer.describe(image, prompt=prompt)
        try:
            for event in events:
                if event.done and event.result:
                    self.store.set(key, event.result.encode("utf-8"))
                yield event
        finally:
            events.close()


class DescribeStep:
    """Asks `describer` for a description of the input image and writes it
    to a temp .txt file. Satisfies ProgressStep[Path]."""

    def __init__(self, describer: Describer, prompt: str) -> None:
        self.describer = describer
        self.prompt = prompt

    def run(self, input_path: Path) -> ProgressStream[Path]:
        events = self.describer.describe(input_path, prompt=self.prompt)
        return land_text_stream(events, ".txt")
