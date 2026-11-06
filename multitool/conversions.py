"""jpgize and mp4ize as Job steps: convert a file next to itself, keeping
its timestamps (and, for images, its metadata)."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from filejobs.pipeline import (
    Job,
    ProgressStep,
    suffix_destination,
    temp_output_path,
)
from filejobs.progress import BaseProgressReporter, ProgressEvent, ProgressStream
from filejobs.runners import FFMpegRunner
from multitool.external import ExifTool, ImageMagick

LOGGER = logging.getLogger(__name__)

# Tried in order: copy the audio stream as is, else re-encode it.
AUDIO_CODECS = ("copy", "aac")


class JpegConversionStep:
    """Any image ImageMagick reads -> upright JPEG with the source's tags."""

    def __init__(self, magick: ImageMagick, exiftool: ExifTool) -> None:
        self.magick = magick
        self.exiftool = exiftool

    def run(self, input_path: Path) -> ProgressStream[Path]:
        produced = temp_output_path("multitool-jpeg-", ".jpg")
        try:
            self.magick.to_jpeg(input_path, produced)
            self.exiftool.copy_tags(input_path, produced)
            shutil.copystat(input_path, produced)
        except BaseException:
            produced.unlink(missing_ok=True)
            raise
        yield ProgressEvent(completed=1, total=1, done=True, result=produced)


class Mp4RemuxStep:
    """Video -> MP4 with the video stream copied; the audio stream is copied
    too, or re-encoded to AAC if MP4 cannot hold it."""

    def __init__(self, ffmpeg: FFMpegRunner) -> None:
        self.ffmpeg = ffmpeg

    def run(self, input_path: Path) -> ProgressStream[Path]:
        produced = temp_output_path("multitool-mp4-", ".mp4")
        duration = self.ffmpeg.probe_duration(input_path)
        try:
            yield from self._remux(input_path, produced, duration)
            shutil.copystat(input_path, produced)
        except BaseException:
            produced.unlink(missing_ok=True)
            raise
        yield ProgressEvent(
            completed=duration or 1, total=duration, done=True, result=produced
        )

    def _remux(
        self, input_path: Path, produced: Path, duration: float | None
    ) -> ProgressStream[Path]:
        failure: RuntimeError | None = None
        for audio_codec in AUDIO_CODECS:
            args = ["-i", str(input_path), "-c:v", "copy", "-c:a", audio_codec]
            try:
                for event in self.ffmpeg.run([*args, str(produced)], duration=duration):
                    if not event.done:
                        yield ProgressEvent(
                            completed=event.completed, total=event.total
                        )
            except RuntimeError as exc:
                LOGGER.info("%s: audio codec %s failed", input_path, audio_codec)
                failure = exc
            else:
                return
        raise RuntimeError(f"could not remux to mp4: {failure}")


@dataclass(frozen=True, slots=True)
class Conversion:
    source: Path
    destination: Path
    remove_source: bool

    def describe(self) -> str:
        action = f"convert {self.source} -> {self.destination}"
        return f"{action}, then remove {self.source}" if self.remove_source else action


def plan_conversions(
    sources: Iterable[Path], extension: str, remove_source: bool
) -> list[Conversion]:
    """One conversion per source, landing at source.<extension>."""
    destination_of = suffix_destination(extension)
    return [
        Conversion(
            source=source,
            destination=destination_of(source),
            remove_source=remove_source,
        )
        for source in sources
    ]


def run_conversion(
    conversion: Conversion,
    step: ProgressStep[Path],
    reporter: BaseProgressReporter,
    *,
    overwrite: bool,
) -> Path:
    """Run `step` on the source as a Job, then remove the source if asked.
    Returns the written destination."""
    if conversion.source.suffix.lower() == conversion.destination.suffix.lower():
        raise ValueError(f"already a {conversion.destination.suffix} file")
    job = Job(
        steps=[(step, f"Converting {conversion.source.name}")],
        dest_fn=lambda _source: conversion.destination,
    )
    written = job.run(conversion.source, reporter, overwrite=overwrite)
    if conversion.remove_source:
        conversion.source.unlink()
    return written
