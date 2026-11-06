"""Transcribe task: the steps from video/audio to a subtitle/text sidecar.

AudioExtractor feeds TranscribeStep, which drives a Transcriber backend and
renders its segments with one of FORMATTERS. The subprocess-runner
primitives they're built on (FFMpegRunner) live in filejobs/runners.py since
those are reusable outside this task. The command is
glados/commands/transcribe.py.
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

from filejobs.progress import ProgressEvent, ProgressStream
from filejobs.runners import CliArgs, FFMpegRunner
from glados.tasks.protocols import Transcriber, TranscriptSegment

DEFAULT_OUTPUT_FORMAT = "txt"


# --------------------------------------------------------------------------
# Format rendering: segments to srt, vtt, txt, json, csv or lrc text
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
    ProgressStep[Path] — plugs directly into filejobs.pipeline.Job."""

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
