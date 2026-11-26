"""tag: text or a file -> its kind, a three- or four-word description and up
to three hashtags.

There is no tag backend: Tagger composes other tasks, all with tag's own
prompt. Images go to describe in one call; audio and video are extracted
(only the first seconds, unless told otherwise), transcribed and sent to
rewrite; text, and a document's name and media type, go to rewrite. The kind
comes from the file name, never from the model. The model's reply is a JSON
object, validated here; the result is cached by everything that changes it.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import pydantic
from foundation.cache import CacheMissError

from filejobs.pipeline import ProgressStep, consume_stream
from filejobs.progress import BaseProgressReporter
from oddjob.lib.cache import ByteStore, cache_key, file_sha256
from oddjob.lib.describe import SECRET_OPTIONS
from oddjob.lib.media import is_image, is_video
from oddjob.lib.protocols import Describer, Rewriter, Transcriber

CACHE_TOOL = "tag"
# Bumped when the cached value's layout changes, so old entries are misses.
CACHE_LAYOUT_VERSION = "1"

# shortcut: text beyond this many characters is not sent; raise it, or send
# a summary, if long texts get poor tags.
TEXT_LIMIT = 8000
MAX_HASHTAGS = 3

LOGGER = logging.getLogger(__name__)


class ContentKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    # Never detected: tag gets no URLs. Callers force it with --type.
    LINK = "link"


def media_type_of(path: Path) -> str | None:
    return mimetypes.guess_type(path.name, strict=False)[0]


def kind_of(path: Path) -> ContentKind:
    """The kind of `path`, from its name."""
    if is_video(path):
        return ContentKind.VIDEO
    if is_image(path):
        return ContentKind.IMAGE
    media_type = media_type_of(path) or ""
    if media_type.startswith("audio/"):
        return ContentKind.AUDIO
    if media_type.startswith("text/"):
        return ContentKind.TEXT
    return ContentKind.DOCUMENT


@dataclass(frozen=True, slots=True)
class TagResult:
    kind: ContentKind
    description: str
    hashtags: tuple[str, ...]


class _Reply(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(strict=True)

    description: str
    hashtags: list[str]


def normalize_hashtags(tags: Iterable[str]) -> tuple[str, ...]:
    """`#tag`s Telegram can search: lowercase, accents kept, anything but
    letters, digits and `_` dropped, no duplicates, at most MAX_HASHTAGS."""
    normalized: list[str] = []
    for tag in tags:
        word = "".join(c for c in tag.lower() if c.isalnum() or c == "_")
        if word and f"#{word}" not in normalized:
            normalized.append(f"#{word}")
    return tuple(normalized[:MAX_HASHTAGS])


def _first_json_object(reply: str) -> object:
    decoder = json.JSONDecoder()
    start = reply.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(reply, start)
        except json.JSONDecodeError:
            start = reply.find("{", start + 1)
            continue
        return value
    raise ValueError(f"no JSON object in the model's reply: {reply[:80]!r}")


def parse_reply(reply: str, kind: ContentKind) -> TagResult:
    """The first JSON object in `reply` (bare, fenced or within prose) as a
    TagResult of `kind`. Raises ValueError if there is none or it is not
    {"description": str, "hashtags": [str, ...]}."""
    try:
        parsed = _Reply.model_validate(_first_json_object(reply))
    except pydantic.ValidationError as exc:
        raise ValueError(f"unexpected reply from the model: {exc}") from exc
    description = " ".join(parsed.description.split())
    if not description:
        raise ValueError("the model's reply has an empty description")
    return TagResult(kind, description, normalize_hashtags(parsed.hashtags))


def encode_result(result: TagResult) -> bytes:
    """The cached form of `result`, read back with parse_reply."""
    value = {"description": result.description, "hashtags": list(result.hashtags)}
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class TaskBackends(Protocol):
    """The backends of the tasks tag composes, each built on first use, and
    the name and options each would run with (for the cache key)."""

    def rewriter(self) -> Rewriter: ...

    def describer(self) -> Describer: ...

    def transcriber(self) -> Transcriber: ...

    def settings(self, task: str) -> tuple[str, Mapping[str, Any]]: ...


def user_message(
    *,
    context: str | None,
    name: str | None = None,
    media_type: str | None = None,
    body: tuple[str, str] | None = None,
) -> str:
    """What rewrite receives: the file's name and type, the context and a
    labelled body (text or transcript), each only when present."""
    lines: list[str] = []
    if name:
        lines.append(f"File name: {name}")
    if media_type:
        lines.append(f"Media type: {media_type}")
    if context:
        lines.append(f"Context: {context}")
    if body:
        label, content = body
        lines.append(f"{label}:\n{content}")
    return "\n".join(lines)


class Tagger:
    """Tags text and files through `backends`, with `prompt` (tag's system
    prompt, already rendered) for every model call. `store` caches results
    (None: no cache); audio and video are cut to `max_duration` seconds by
    the `extractor` (None: the whole audio)."""

    def __init__(
        self,
        backends: TaskBackends,
        prompt: str,
        *,
        store: ByteStore | None,
        max_duration: float | None,
        extractor: Callable[[], ProgressStep[Path]],
    ) -> None:
        self.backends = backends
        self.prompt = prompt
        self.store = store
        self.max_duration = max_duration
        self.make_extractor = extractor
        self._rewriter: Rewriter | None = None
        self._describer: Describer | None = None
        self._transcriber: Transcriber | None = None

    def tag_text(
        self, text: str, context: str | None, reporter: BaseProgressReporter
    ) -> TagResult:
        message = user_message(context=context, body=("Text", text[:TEXT_LIMIT]))
        return self._tagged(
            ContentKind.TEXT,
            ["text", text, context or ""],
            ("rewrite",),
            lambda: self._rewrite(message, reporter),
        )

    def tag_file(
        self, path: Path, context: str | None, reporter: BaseProgressReporter
    ) -> TagResult:
        kind = kind_of(path)
        identity = [path.name, file_sha256(path), context or ""]
        if kind is ContentKind.IMAGE:
            return self._tagged(
                kind,
                identity,
                ("describe",),
                lambda: self._describe(path, context, reporter),
            )
        if kind in (ContentKind.AUDIO, ContentKind.VIDEO):
            duration = "full" if self.max_duration is None else f"{self.max_duration:g}"
            return self._tagged(
                kind,
                [*identity, duration],
                ("transcribe", "rewrite"),
                lambda: self._rewrite(
                    self._media_message(path, context, reporter), reporter
                ),
            )
        media_type = media_type_of(path)
        body = None
        if kind is ContentKind.TEXT:
            text = path.read_text(encoding="utf-8", errors="replace")
            body = ("Text", text[:TEXT_LIMIT])
        message = user_message(
            context=context, name=path.name, media_type=media_type, body=body
        )
        return self._tagged(
            kind, identity, ("rewrite",), lambda: self._rewrite(message, reporter)
        )

    def _tagged(
        self,
        kind: ContentKind,
        identity: list[str],
        tasks: tuple[str, ...],
        ask: Callable[[], str],
    ) -> TagResult:
        """The cached result for this content, else the parsed reply of
        `ask`, stored only once it parses."""
        if self.store is None:
            return parse_reply(ask(), kind)
        key = self._key(kind, identity, tasks)
        try:
            cached = self.store.get(key)
        except CacheMissError:
            pass
        else:
            try:
                return parse_reply(cached.decode("utf-8"), kind)
            except ValueError as exc:
                LOGGER.warning("ignoring unreadable cached tags: %s", exc)
        result = parse_reply(ask(), kind)
        self.store.set(key, encode_result(result))
        return result

    def _key(
        self, kind: ContentKind, identity: list[str], tasks: tuple[str, ...]
    ) -> str:
        settings = {}
        for task in tasks:
            backend, options = self.backends.settings(task)
            public = {k: v for k, v in options.items() if k not in SECRET_OPTIONS}
            settings[task] = [backend, public]
        return cache_key(
            CACHE_TOOL,
            CACHE_LAYOUT_VERSION,
            kind.value,
            *identity,
            self.prompt,
            json.dumps(settings, sort_keys=True, default=str),
        )

    def _rewrite(self, message: str, reporter: BaseProgressReporter) -> str:
        if self._rewriter is None:
            self._rewriter = self.backends.rewriter()
        events = self._rewriter.rewrite(message, prompt=self.prompt)
        return consume_stream(events, reporter, "Tagging")

    def _describe(
        self, image: Path, context: str | None, reporter: BaseProgressReporter
    ) -> str:
        if self._describer is None:
            self._describer = self.backends.describer()
        # describe takes no user text, so the context rides in the prompt.
        prompt = f"{self.prompt}\n\nContext: {context}" if context else self.prompt
        events = self._describer.describe(image, prompt=prompt)
        return consume_stream(events, reporter, "Tagging")

    def _media_message(
        self, media: Path, context: str | None, reporter: BaseProgressReporter
    ) -> str:
        if self._transcriber is None:
            self._transcriber = self.backends.transcriber()
        audio = consume_stream(
            self.make_extractor().run(media), reporter, "Extracting audio"
        )
        try:
            segments = consume_stream(
                self._transcriber.transcribe(audio, language=None),
                reporter,
                "Transcribing",
            )
        finally:
            audio.unlink(missing_ok=True)
        transcript = " ".join(segment.text.strip() for segment in segments)
        return user_message(
            context=context,
            name=media.name,
            media_type=media_type_of(media),
            body=("Transcript", transcript[:TEXT_LIMIT]),
        )
