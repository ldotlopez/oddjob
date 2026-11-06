"""Local whisper.cpp CLI backend: implements transcribe.

Global options (`[backends.whisper]` in the config, or `-m/--model`):
`model` (path to a ggml model) and `binary` (the whisper-cli executable).
The model and binary are checked when a transcription starts, not when the
backend is built.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pydantic
from platformdirs import user_data_dir

from glados.core.progress import ProgressEvent, ProgressStream
from glados.core.runners import CliArgs
from glados.tasks.protocols import Transcriber, TranscriptSegment

DEFAULT_MODEL = Path(user_data_dir("whisper", appauthor=False)) / "default-model.bin"


class WhisperOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    model: Path = DEFAULT_MODEL
    binary: str = "whisper-cli"

    @pydantic.field_validator("model")
    @classmethod
    def _expand_user(cls, value: Path) -> Path:
        return value.expanduser()


class WhisperCliRunner:
    """Runs whisper-cli with arbitrary arguments, yielding ProgressEvent
    parsed from `--print-progress` output.

    `--print-progress` is added here; everything else about the invocation
    (model, language, output format/prefix, input file) is the caller's.
    """

    _PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")

    def __init__(self, whisper_bin: str) -> None:
        self.whisper_bin = whisper_bin

    def run(self, args: CliArgs) -> ProgressStream:
        if shutil.which(self.whisper_bin) is None:
            raise FileNotFoundError(
                f"whisper binary not found on PATH: {self.whisper_bin}"
            )

        cmd = [self.whisper_bin, "--print-progress", *args]

        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        stderr_lines: list[str] = []
        completed = 0.0
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)
                match = self._PROGRESS_RE.search(line)
                if match:
                    completed = float(match.group(1))
                    yield ProgressEvent(completed=completed, total=100)
        except GeneratorExit:
            proc.terminate()
            raise
        finally:
            if proc.stderr:
                proc.stderr.close()
            proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"whisper-cli failed: {''.join(stderr_lines).strip()}")

        yield ProgressEvent(completed=100, total=100, done=True)


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


class WhisperBackend:
    """Always requests JSON output from whisper-cli (`-ojson`) and parses
    it into TranscriptSegments; formatting (srt/vtt/...) is the task's."""

    def __init__(self, options: WhisperOptions) -> None:
        self.options = options
        self.runner = WhisperCliRunner(options.binary)

    def transcribe(
        self, audio_path: Path, *, language: str | None
    ) -> ProgressStream[list[TranscriptSegment]]:
        model = self.options.model
        if not model.is_file():
            raise FileNotFoundError(
                f"whisper model not found: {model} (set [backends.whisper] model"
                " in the config, or pass -m/--model)"
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
            str(model),
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


def __glados_plugin__(options: Mapping[str, Any]) -> list[tuple[str, type, object]]:
    """Build the backend with its global options; one triple per task it
    implements, named after the task (see core/backends.py)."""
    backend = WhisperBackend(WhisperOptions.model_validate(options))
    return [("transcribe", Transcriber, backend)]
