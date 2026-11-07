"""Protocol contracts between backends and tasks — one Protocol per task,
matching backends structurally (no inheritance required). Each backend's
`__glados_plugin__` entry point returns its object once per task it
implements, under that task's Protocol (see plugins/whisper.py).

Transcriber is implemented by plugins/whisper.py; Rewriter, Summarizer,
Expander, Translator and Describer by plugins/openai.py, plugins/ollama.py
and plugins/llm.py, all through tasks/text_backend.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from filejobs.progress import ProgressStream


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(
        self, audio_path: Path, *, language: str | None
    ) -> ProgressStream[list[TranscriptSegment]]: ...


# --------------------------------------------------------------------------
# Text tasks
# --------------------------------------------------------------------------
#
# Kept as distinct Protocols rather than one generic "text
# transform" so each task checks its backend against exactly what it
# calls, even though one backend class (tasks.text_backend.TextBackend)
# satisfies them all. `prompt` is the task's system prompt, already
# rendered from `[prompts]` in the config (core.config.Prompts); the
# backend sends it as-is with `text` as the user message.


@runtime_checkable
class Rewriter(Protocol):
    def rewrite(self, text: str, *, prompt: str) -> ProgressStream[str]: ...


@runtime_checkable
class Summarizer(Protocol):
    def summarize(self, text: str, *, prompt: str) -> ProgressStream[str]: ...


@runtime_checkable
class Expander(Protocol):
    def expand(self, text: str, *, prompt: str) -> ProgressStream[str]: ...


@runtime_checkable
class Translator(Protocol):
    def translate(self, text: str, *, prompt: str) -> ProgressStream[str]: ...


@runtime_checkable
class Describer(Protocol):
    def describe(self, image: Path, *, prompt: str) -> ProgressStream[str]: ...
