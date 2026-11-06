"""Transcribe task: video/audio -> subtitle/text sidecar via a Transcriber
backend.

FORMATTERS and AudioExtractor are transcribe-specific and stay here; the
subprocess-runner primitives they're built on (FFMpegRunner) live in
core/runners.py since those are reusable outside this task.

Backend resolution has two paths, because foundation.plugin.Register's
entry points are called with no arguments (see BaseRegister.register) —
per-invocation configuration like -m/--model can't flow through
registration itself:
  - No -m/--model given: use the Register-discovered default instance
    (backends_for(Transcriber)) — whatever model that backend's own
    register() configured it with.
  - -m/--model given: bypass Register for that one call and construct
    the backend class directly with the requested model. _DIRECT_FACTORIES
    is the (small, manually maintained) map from backend name to
    constructor needed only for this override path.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import rich_click as click

from glados.backends.whisper_backend import WhisperCliBackend
from glados.core.backend_discovery import backends_for
from glados.core.cli_common import (
    GladosContext,
    backend_option,
    common_file_options,
    model_option,
    pass_glados_context,
)
from glados.core.pipeline import Job, override_destination, suffix_destination
from glados.core.progress import ProgressEvent, ProgressStream
from glados.core.runners import CliArgs, FFMpegRunner
from glados.tasks.protocols import Transcriber, TranscriptSegment

DEFAULT_OUTPUT_FORMAT = "srt"


# --------------------------------------------------------------------------
# Format rendering (unchanged from transcribe_sidecar.py)
# --------------------------------------------------------------------------


def _format_srt_timestamp(seconds: float) -> str:
    total_milliseconds = round(seconds * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def _format_vtt_timestamp(seconds: float) -> str:
    total_milliseconds = round(seconds * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _format_lrc_timestamp(seconds: float) -> str:
    total_centiseconds = round(seconds * 100)
    minutes, remainder = divmod(total_centiseconds, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _format_srt(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        lines.append(str(index))
        lines.append(
            f"{_format_srt_timestamp(segment.start)} --> {_format_srt_timestamp(segment.end)}"
        )
        lines.append(segment.text.strip())
        lines.append("")
    return "\n".join(lines)


def _format_vtt(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for segment in segments:
        lines.append(
            f"{_format_vtt_timestamp(segment.start)} --> {_format_vtt_timestamp(segment.end)}"
        )
        lines.append(segment.text.strip())
        lines.append("")
    return "\n".join(lines)


def _format_txt(segments: list[TranscriptSegment]) -> str:
    return "\n".join(segment.text.strip() for segment in segments)


def _format_json(segments: list[TranscriptSegment]) -> str:
    payload = [
        {"start": segment.start, "end": segment.end, "text": segment.text.strip()}
        for segment in segments
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _format_csv(segments: list[TranscriptSegment]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["start", "end", "text"])
    for segment in segments:
        writer.writerow([segment.start, segment.end, segment.text.strip()])
    return buffer.getvalue()


def _format_lrc(segments: list[TranscriptSegment]) -> str:
    return "\n".join(
        f"[{_format_lrc_timestamp(segment.start)}]{segment.text.strip()}"
        for segment in segments
    )


type SegmentFormatter = Callable[[list[TranscriptSegment]], str]

FORMATTERS: dict[str, SegmentFormatter] = {
    "srt": _format_srt,
    "vtt": _format_vtt,
    "txt": _format_txt,
    "json": _format_json,
    "csv": _format_csv,
    "lrc": _format_lrc,
}


# --------------------------------------------------------------------------
# Pipeline steps
# --------------------------------------------------------------------------


class AudioExtractor:
    """Extracts the first audio stream to a temporary mono 16kHz WAV file.
    Satisfies ProgressStep[Path]."""

    def __init__(self, runner: FFMpegRunner | None = None) -> None:
        self.runner = runner or FFMpegRunner()

    def run(self, input_path: Path) -> ProgressStream[Path]:
        file_descriptor, extracted_audio_path_str = tempfile.mkstemp(
            prefix="whisper-audio-", suffix=".wav"
        )
        os.close(file_descriptor)
        extracted_audio_path = Path(extracted_audio_path_str)

        duration = self.runner.probe_duration(input_path)
        args: CliArgs = [
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(extracted_audio_path),
        ]

        events = self.runner.run(args, duration=duration)
        try:
            for event in events:
                yield (
                    replace(event, result=extracted_audio_path) if event.done else event
                )
        except BaseException:
            events.close()
            extracted_audio_path.unlink(missing_ok=True)
            raise


class TranscribeStep:
    """Drives a Transcriber backend, then renders the result into the
    requested output format and writes it to a temp file. Satisfies
    ProgressStep[Path] — plugs directly into core.pipeline.Job."""

    def __init__(
        self, backend: Transcriber, language: str | None, output_format: str
    ) -> None:
        if output_format not in FORMATTERS:
            raise ValueError(
                f"unsupported output format: {output_format} (choose from: {', '.join(FORMATTERS)})"
            )
        self.backend = backend
        self.language = language
        self.output_format = output_format

    def run(self, input_path: Path) -> ProgressStream[Path]:
        events = self.backend.transcribe(input_path, language=self.language)
        final_event: ProgressEvent[list[TranscriptSegment]] | None = None
        try:
            for event in events:
                if event.done:
                    final_event = event
                else:
                    yield event
        except BaseException:
            events.close()
            raise

        if final_event is None or final_event.result is None:
            raise RuntimeError(
                "transcription backend ended without producing a transcript"
            )

        content = FORMATTERS[self.output_format](final_event.result)

        file_descriptor, output_path_str = tempfile.mkstemp(
            prefix="whisper-out-", suffix=f".{self.output_format}"
        )
        os.close(file_descriptor)
        output_path = Path(output_path_str)
        try:
            output_path.write_text(content, encoding="utf-8")
        except BaseException:
            output_path.unlink(missing_ok=True)
            raise

        yield replace(final_event, result=output_path)


# --------------------------------------------------------------------------
# Backend resolution
# --------------------------------------------------------------------------

_DEFAULT_BACKENDS: dict[str, Transcriber] = backends_for(Transcriber)
DEFAULT_BACKEND = "whisper" if "whisper" in _DEFAULT_BACKENDS else None

# See this module's docstring — only needed for the -m/--model override path.
_DIRECT_FACTORIES: dict[str, Callable[[Path], Transcriber]] = {
    "whisper": lambda model: WhisperCliBackend(model=model),
}


def _resolve_backend(name: str, model: Path | None) -> Transcriber:
    if model is not None:
        try:
            factory = _DIRECT_FACTORIES[name]
        except KeyError:
            raise ValueError(
                f"backend {name!r} has no direct constructor for -m/--model overrides"
            ) from None
        return factory(model)
    try:
        return _DEFAULT_BACKENDS[name]
    except KeyError:
        raise ValueError(f"unknown or unavailable backend: {name}") from None


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------
#
# This same click.Command object is both `glados transcribe ...`
# (cli.py adds it to the group) and the standalone `transcribe ...` tool
# (pyproject.toml points [project.scripts] straight at it) — no separate
# argparse-style add_subparser()/main() split needed.


@click.command("transcribe")
@click.argument("input_path", type=click.Path(path_type=Path))
@model_option
@click.option(
    "-l",
    "--language",
    default=None,
    help="audio language code, e.g. en, es (default: auto-detect)",
)
@click.option(
    "-f",
    "--format",
    "output_format",
    type=click.Choice(sorted(FORMATTERS)),
    default=DEFAULT_OUTPUT_FORMAT,
    help=f"output format (default: {DEFAULT_OUTPUT_FORMAT})",
)
@backend_option(_DEFAULT_BACKENDS, DEFAULT_BACKEND)
@common_file_options
@pass_glados_context
def cli(
    ctx: GladosContext,
    input_path: Path,
    model: Path | None,
    language: str | None,
    output_format: str,
    backend: str,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Extract audio and transcribe INPUT_PATH to a subtitle/text sidecar."""
    try:
        backend_instance = _resolve_backend(backend, model)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    job = Job(
        steps=[
            (AudioExtractor(), "Extracting audio"),
            (
                TranscribeStep(
                    backend_instance, language=language, output_format=output_format
                ),
                "Transcribing",
            ),
        ],
        dest_fn=override_destination(output, suffix_destination(output_format)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
