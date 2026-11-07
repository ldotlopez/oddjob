"""Local whisper CLI backends: both implement transcribe.

- `whisper_cpp`: whisper.cpp's `whisper-cli`. Options (`[backends.whisper_cpp]`,
  or `-m/--model`): `model` (path to a ggml model) and `binary`.
- `whisper`: OpenAI's `whisper` CLI (`openai-whisper`). Options
  (`[backends.whisper]`, or `-m/--model`): `model` (a model name such as
  `turbo`, or a path to a `.pt` checkpoint) and `binary`.

Both always request JSON output and parse it into TranscriptSegments;
formatting (srt/vtt/...) is the task's. Models and binaries are checked when
a transcription starts, not when the backend is built.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pydantic
from platformdirs import user_data_dir

from filejobs.progress import ProgressEvent, ProgressStream
from filejobs.runners import CliArgs
from oddjob.lib.protocols import Transcriber, TranscriptSegment

LOGGER = logging.getLogger(__name__)

DEFAULT_CPP_MODEL = (
    Path(user_data_dir("whisper", appauthor=False)) / "default-model.bin"
)
DEFAULT_OPENAI_MODEL = "turbo"

type SegmentParser = Callable[[Path], list[TranscriptSegment]]


class WhisperCliRunner:
    """Runs a whisper CLI with arbitrary arguments, yielding ProgressEvent
    parsed from its stderr with `progress_re` (first group: percentage).

    The caller supplies every argument, including whatever flag makes the
    binary report progress. Carriage-return-updated bars (tqdm) work too:
    text-mode pipes treat `\\r` as a line ending.
    """

    def __init__(self, binary: str, progress_re: re.Pattern[str]) -> None:
        self.binary = binary
        self.progress_re = progress_re

    def run(self, args: CliArgs) -> ProgressStream:
        if shutil.which(self.binary) is None:
            raise FileNotFoundError(f"whisper binary not found on PATH: {self.binary}")

        cmd = [self.binary, *args]
        LOGGER.debug("running: %s", shlex.join(cmd))

        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        stderr_lines: list[str] = []
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)
                match = self.progress_re.search(line)
                if match:
                    yield ProgressEvent(completed=float(match.group(1)), total=100)
        except GeneratorExit:
            proc.terminate()
            raise
        finally:
            if proc.stderr:
                proc.stderr.close()
            proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"{self.binary} failed: {''.join(stderr_lines).strip()}")

        yield ProgressEvent(completed=100, total=100, done=True)


def _with_segments(
    events: ProgressStream, json_path: Path, parse: SegmentParser
) -> ProgressStream[list[TranscriptSegment]]:
    """Pass `events` through, attaching the segments parsed from
    `json_path` to the final one. Closes `events` if interrupted."""
    try:
        for event in events:
            if not event.done:
                yield event
                continue
            if not json_path.is_file():
                raise RuntimeError(f"expected whisper output not found: {json_path}")
            yield replace(event, result=parse(json_path))
    except BaseException:
        events.close()
        raise


# --------------------------------------------------------------------------
# whisper.cpp (whisper-cli)
# --------------------------------------------------------------------------


class WhisperCppOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    model: Path = DEFAULT_CPP_MODEL
    binary: str = "whisper-cli"

    @pydantic.field_validator("model")
    @classmethod
    def _expand_user(cls, value: Path) -> Path:
        return value.expanduser()


def _parse_whisper_cpp_json(json_path: Path) -> list[TranscriptSegment]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    return [
        TranscriptSegment(
            start=item["offsets"]["from"] / 1000.0,
            end=item["offsets"]["to"] / 1000.0,
            text=item["text"].strip(),
        )
        for item in payload["transcription"]
    ]


class WhisperCppBackend:
    """whisper-cli with `--output-json --output-file PREFIX`, progress from
    `--print-progress`."""

    _PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")

    def __init__(self, options: WhisperCppOptions) -> None:
        self.options = options
        self.runner = WhisperCliRunner(options.binary, self._PROGRESS_RE)

    def transcribe(
        self, audio_path: Path, *, language: str | None
    ) -> ProgressStream[list[TranscriptSegment]]:
        model = self.options.model
        if not model.is_file():
            raise FileNotFoundError(
                f"whisper.cpp model not found: {model} (set [backends.whisper_cpp]"
                " model in the config, or pass -m/--model)"
            )

        file_descriptor, json_prefix_str = tempfile.mkstemp(prefix="whisper-json-")
        os.close(file_descriptor)
        json_prefix = Path(json_prefix_str)
        json_prefix.unlink()
        json_path = json_prefix.with_suffix(".json")

        # Long options only: whisper-cli exits 0 on an unknown argument, so a
        # misspelt short flag fails silently. Its default language is `en`,
        # hence `auto` when none is given.
        args: CliArgs = [
            "--print-progress",
            "--file",
            str(audio_path),
            "--output-json",
            "--output-file",
            str(json_prefix),
            "--model",
            str(model),
            "--language",
            language or "auto",
        ]

        try:
            yield from _with_segments(
                self.runner.run(args), json_path, _parse_whisper_cpp_json
            )
        finally:
            json_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# OpenAI whisper (openai-whisper's `whisper` CLI)
# --------------------------------------------------------------------------


class OpenAIWhisperOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    model: str = DEFAULT_OPENAI_MODEL
    binary: str = "whisper"


def _parse_openai_whisper_json(json_path: Path) -> list[TranscriptSegment]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    return [
        TranscriptSegment(
            start=float(item["start"]),
            end=float(item["end"]),
            text=item["text"].strip(),
        )
        for item in payload["segments"]
    ]


class OpenAIWhisperBackend:
    """whisper with `--output_format json --output_dir DIR` (written as
    `DIR/<audio stem>.json`); `--verbose False` makes it draw a tqdm bar on
    stderr, which is the progress source."""

    _PROGRESS_RE = re.compile(r"(\d+)%\|")

    def __init__(self, options: OpenAIWhisperOptions) -> None:
        self.options = options
        self.runner = WhisperCliRunner(options.binary, self._PROGRESS_RE)

    def transcribe(
        self, audio_path: Path, *, language: str | None
    ) -> ProgressStream[list[TranscriptSegment]]:
        with tempfile.TemporaryDirectory(prefix="whisper-json-") as output_dir_str:
            output_dir = Path(output_dir_str)
            args: CliArgs = [
                str(audio_path),
                "--model",
                self.options.model,
                "--output_format",
                "json",
                "--output_dir",
                str(output_dir),
                "--verbose",
                "False",
            ]
            if language:
                args += ["--language", language]

            json_path = output_dir / f"{audio_path.stem}.json"
            yield from _with_segments(
                self.runner.run(args), json_path, _parse_openai_whisper_json
            )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


type BackendFactory = Callable[[Mapping[str, Any]], Transcriber]

_FACTORIES: dict[str, BackendFactory] = {
    "whisper": lambda options: OpenAIWhisperBackend(
        OpenAIWhisperOptions.model_validate(options)
    ),
    "whisper_cpp": lambda options: WhisperCppBackend(
        WhisperCppOptions.model_validate(options)
    ),
}


def __oddjob_plugin__(
    backend: str, options: Mapping[str, Any]
) -> list[tuple[str, type, object]]:
    """Build `backend` with its global options; one triple per task it
    implements, named after the task (see core/backends.py)."""
    try:
        factory = _FACTORIES[backend]
    except KeyError:
        raise ValueError(
            f"module {__name__} provides no backend {backend!r}"
            f" (provides: {', '.join(sorted(_FACTORIES))})"
        ) from None
    return [("transcribe", Transcriber, factory(options))]
