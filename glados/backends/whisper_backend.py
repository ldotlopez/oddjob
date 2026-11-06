"""Local whisper.cpp CLI backend — the only Transcriber implementation today.

Two layers of deferred validation are stacked here, each closing a
different gap:
  - The "model file exists" check moved from WhisperCliBackend.__init__
    to the first call to transcribe() (vs. the original
    transcribe_sidecar.py) — construction shouldn't fail just because a
    model isn't configured yet.
  - The "whisper-cli binary is on PATH" check moved from
    WhisperCliRunner.__init__ to its run() (see core/runners.py) — same
    reasoning, one level lower.
  - register() (bottom of this file) wraps construction in Lazy, so
    neither check even runs unless something actually queries for a
    Transcriber — register() itself may run at process-import time
    regardless of whether transcribe is used this invocation.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from foundation.plugin import Lazy
from platformdirs import user_data_dir

from glados.core.progress import ProgressStream
from glados.core.runners import CliArgs, WhisperCliRunner
from glados.tasks.protocols import Transcriber, TranscriptSegment

DEFAULT_MODEL = Path(user_data_dir("whisper", appauthor=False)) / "default-model.bin"


def _parse_whisper_json(json_path: Path) -> list[TranscriptSegment]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    return [
        TranscriptSegment(
            start=item["offsets"]["from"] / 1000.0,
            end=item["offsets"]["to"] / 1000.0,
            text=item["text"].strip(),
        )
        for item in payload["transcription"]
    ]


class WhisperCliBackend:
    """Always requests JSON output from whisper-cli (`-ojson`) and parses
    it into TranscriptSegments — task-side formatting (srt/vtt/...) lives
    in tasks/transcribe.py, not here."""

    def __init__(
        self, model: Path | None = None, runner: WhisperCliRunner | None = None
    ) -> None:
        self.runner = runner or WhisperCliRunner()
        self.model = model if model is not None else DEFAULT_MODEL

    def transcribe(
        self, audio_path: Path, *, language: str | None
    ) -> ProgressStream[list[TranscriptSegment]]:
        if not self.model.is_file():
            raise FileNotFoundError(
                f"whisper model not found: {self.model} "
                "(place a model there, or pass -m/--model explicitly)"
            )

        file_descriptor, json_prefix_str = tempfile.mkstemp(prefix="whisper-json-")
        os.close(file_descriptor)
        json_prefix = Path(json_prefix_str)
        json_prefix.unlink()

        args: CliArgs = [
            "-f",
            str(audio_path),
            "-ojson",
            "-of",
            str(json_prefix),
            "-m",
            str(self.model),
        ]
        if language:
            args += ["-l", language]

        json_path = json_prefix.with_suffix(".json")

        events = self.runner.run(args)
        try:
            for event in events:
                if event.done:
                    if not json_path.is_file():
                        raise RuntimeError(
                            f"expected whisper output not found: {json_path}"
                        )
                    yield replace(event, result=_parse_whisper_json(json_path))
                else:
                    yield event
        except BaseException:
            events.close()
            raise
        finally:
            json_path.unlink(missing_ok=True)


def register() -> list[tuple[str, type, object]]:
    """Entry point read by foundation.plugin.Register (see
    core/backend_discovery.py) — returns (name, Protocol, instance)
    triples, one per Protocol this backend satisfies. Called with no
    arguments, so this instance is built with whatever WhisperCliBackend's
    own defaults are (env/config-driven, not CLI flags) — see
    tasks/transcribe.py's module docstring for how a per-invocation
    -m/--model override is handled instead.

    Wrapped in Lazy: construction (and WhisperCliRunner's own setup)
    only happens if something actually queries for a Transcriber,
    not merely because this module got registered — see Lazy's
    docstring in foundation.plugin for why that distinction matters.
    """
    return [("whisper", Transcriber, Lazy(WhisperCliBackend))]
