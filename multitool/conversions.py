"""jpgize and mp4ize: convert files next to themselves, keeping their
timestamps (and, for images, their metadata)."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from glados.core.pipeline import check_destination, move_to_destination
from glados.core.runners import FFMpegRunner
from multitool.external import ExifTool, ImageMagick
from multitool.files import temp_sibling

LOGGER = logging.getLogger(__name__)

# Tried in order: copy the audio stream as is, else re-encode it.
AUDIO_CODECS = ("copy", "aac")


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
    return [
        Conversion(
            source=source,
            destination=source.with_suffix(extension),
            remove_source=remove_source,
        )
        for source in sources
    ]


def _check_conversion(conversion: Conversion, overwrite: bool) -> None:
    if conversion.source.suffix.lower() == conversion.destination.suffix.lower():
        raise ValueError(f"already a {conversion.destination.suffix} file")
    check_destination(conversion.destination, overwrite)


def _finish(conversion: Conversion, produced: Path, overwrite: bool) -> None:
    shutil.copystat(conversion.source, produced)
    move_to_destination(produced, conversion.destination, overwrite)
    if conversion.remove_source:
        conversion.source.unlink()


def convert_to_jpeg(
    conversion: Conversion,
    magick: ImageMagick,
    exiftool: ExifTool,
    *,
    overwrite: bool,
) -> None:
    _check_conversion(conversion, overwrite)
    with temp_sibling(conversion.destination, ".jpg") as produced:
        magick.to_jpeg(conversion.source, produced)
        exiftool.copy_tags(conversion.source, produced)
        _finish(conversion, produced, overwrite)


def remux_to_mp4(
    conversion: Conversion, ffmpeg: FFMpegRunner, *, overwrite: bool
) -> None:
    """Copy the video stream into an MP4 container; the audio stream is
    copied too, or re-encoded to AAC if MP4 cannot hold it."""
    _check_conversion(conversion, overwrite)
    with temp_sibling(conversion.destination, ".mp4") as produced:
        failure: RuntimeError | None = None
        for audio_codec in AUDIO_CODECS:
            args = ["-i", str(conversion.source), "-c:v", "copy", "-c:a", audio_codec]
            try:
                for _event in ffmpeg.run([*args, str(produced)]):
                    pass
            except RuntimeError as exc:
                LOGGER.info("%s: audio codec %s failed", conversion.source, audio_codec)
                failure = exc
            else:
                break
        else:
            raise RuntimeError(f"could not remux to mp4: {failure}")
        _finish(conversion, produced, overwrite)
