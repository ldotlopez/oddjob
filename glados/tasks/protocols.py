"""Protocol contracts between backends and tasks — one Protocol per task,
matching backends structurally (no inheritance required). Each backend's
`__glados_plugin__` entry point returns its object once per task it
implements, under that task's Protocol (see plugins/whisper.py).

TranscriptSegment/Transcriber are implemented today (tasks/transcribe.py,
plugins/whisper.py). Rewriter/Summarizer/Expander below are
drafted as signatures only — no backend implements them yet; see
tasks/rewrite.py, tasks/summarize.py, tasks/expand.py for the stub steps
and CLI wiring that will grow around them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from glados.core.progress import ProgressStream


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
# Text tasks — signatures only, no implementation yet.
# --------------------------------------------------------------------------
#
# Kept as three distinct Protocols rather than one generic "text
# transform" so each task checks its backend against exactly what it
# calls — even though the shapes are
# structurally similar and a single backend class (e.g. the OpenAI-
# compatible client) is expected to satisfy all three at once.


@runtime_checkable
class Rewriter(Protocol):
    def rewrite(self, text: str, *, instructions: str | None) -> ProgressStream[str]:
        """Rewrite `text` per free-form `instructions` (tone, style,
        audience, ...). `instructions=None` means "improve clarity/
        correctness without changing intent" — the backend's default."""
        ...


@runtime_checkable
class Summarizer(Protocol):
    def summarize(self, text: str, *, max_length: int | None) -> ProgressStream[str]:
        """Summarize `text`, optionally bounded to about `max_length`.
        Unit (words vs. characters) is left to each backend's own
        convention — document it on the concrete implementation."""
        ...


@runtime_checkable
class Expander(Protocol):
    def expand(self, text: str, *, target_length: int | None) -> ProgressStream[str]:
        """Expand `text` toward roughly `target_length`, adding detail/
        examples without changing its meaning. Same unit caveat as
        Summarizer.max_length."""
        ...
