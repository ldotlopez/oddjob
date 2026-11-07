"""audio-grep: run grep over the transcriptions of audio/video files.

Arguments naming an existing directory or audio/video file are the inputs;
every other argument goes to grep unchanged, so grep's own option grammar
never has to be known here. Each input is transcribed (or its transcript
read from the cache), written to a temporary file, and grep runs once over
all of them; the temporary paths in its output become the media paths.

Transcripts are cached (oddjob/lib/cache.py) under `audio-grep/` by a digest
of the file's content, its mtime and the transcription settings. The command
is oddjob/commands/audio_grep.py.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from foundation.cache import CacheMissError

from filejobs.inputs import FileFilter
from filejobs.pipeline import ProgressStep, consume_stream
from filejobs.progress import BaseProgressReporter
from oddjob.lib.cache import ByteStore, cache_key, file_sha256
from oddjob.lib.grep import GrepResult, GrepRunner
from oddjob.lib.protocols import Transcriber, TranscriptSegment
from oddjob.lib.transcribe import FORMATTERS, AudioExtractor

DEFAULT_TRANSCRIPT_FORMAT = "lrc"
CACHE_TOOL = "audio-grep"
# Bumped when the cached value's layout changes, so old entries are misses.
CACHE_LAYOUT_VERSION = "1"

LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Command line: inputs vs. grep arguments
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GrepCommandLine:
    grep_args: tuple[str, ...]
    paths: tuple[Path, ...]


def split_command_line(
    arguments: Sequence[str], is_media: FileFilter
) -> GrepCommandLine:
    """Existing directories and audio/video files are inputs; everything else,
    in order, is for grep."""
    grep_args: list[str] = []
    paths: list[Path] = []
    for argument in arguments:
        path = Path(argument)
        if path.is_dir() or (path.is_file() and is_media(path)):
            paths.append(path)
        else:
            grep_args.append(argument)
    return GrepCommandLine(grep_args=tuple(grep_args), paths=tuple(paths))


# --------------------------------------------------------------------------
# Transcript cache
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranscriptionSettings:
    """What changes a transcript besides the file itself, as given on the
    command line (None: the configured default)."""

    backend: str | None
    model: str | None
    language: str | None


def transcript_key(media: Path, settings: TranscriptionSettings) -> str:
    """Keyed by the content's SHA-256, the mtime and the settings."""
    return cache_key(
        CACHE_TOOL,
        CACHE_LAYOUT_VERSION,
        file_sha256(media),
        str(media.stat().st_mtime_ns),
        settings.backend or "",
        settings.model or "",
        settings.language or "",
    )


def encode_segments(segments: Sequence[TranscriptSegment]) -> bytes:
    payload = [[segment.start, segment.end, segment.text] for segment in segments]
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def decode_segments(value: bytes) -> list[TranscriptSegment]:
    """ValueError if `value` is not what encode_segments wrote."""
    match json.loads(value):
        case list() as payload:
            pass
        case _:
            raise ValueError("cached transcript is not a list")
    segments: list[TranscriptSegment] = []
    for item in payload:
        match item:
            case [int() | float() as start, int() | float() as end, str() as text]:
                segments.append(TranscriptSegment(start=start, end=end, text=text))
            case _:
                raise ValueError(f"malformed cached segment: {item!r}")
    return segments


class CachedTranscripts:
    """Transcript segments of a media file, from the store when cached, else
    from the transcriber, which is only built on the first miss."""

    def __init__(
        self,
        store: ByteStore,
        transcriber: Callable[[], Transcriber],
        settings: TranscriptionSettings,
        extractor: Callable[[], ProgressStep[Path]] = AudioExtractor,
    ) -> None:
        self.store = store
        self.make_transcriber = transcriber
        self.settings = settings
        self.make_extractor = extractor
        self._transcriber: Transcriber | None = None

    def segments(
        self, media: Path, reporter: BaseProgressReporter
    ) -> list[TranscriptSegment]:
        key = transcript_key(media, self.settings)
        try:
            cached = decode_segments(self.store.get(key))
        except CacheMissError:
            pass
        except ValueError as exc:
            LOGGER.warning("%s: ignoring unreadable cached transcript: %s", media, exc)
        else:
            LOGGER.debug("%s: transcript from cache", media)
            return cached
        segments = self._transcribe(media, reporter)
        self.store.set(key, encode_segments(segments))
        return segments

    def _transcribe(
        self, media: Path, reporter: BaseProgressReporter
    ) -> list[TranscriptSegment]:
        if self._transcriber is None:
            self._transcriber = self.make_transcriber()
        audio = consume_stream(
            self.make_extractor().run(media), reporter, "Extracting audio"
        )
        try:
            return consume_stream(
                self._transcriber.transcribe(audio, language=self.settings.language),
                reporter,
                "Transcribing",
            )
        finally:
            audio.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# grep
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transcript:
    media: Path
    segments: list[TranscriptSegment]


def render_transcript(segments: Sequence[TranscriptSegment], output_format: str) -> str:
    """One of transcribe's FORMATTERS, ending in a newline."""
    return FORMATTERS[output_format](list(segments)).rstrip("\n") + "\n"


def grep_transcripts(
    grep: GrepRunner,
    grep_args: Sequence[str],
    transcripts: Sequence[Transcript],
    output_format: str,
) -> GrepResult:
    """Run grep once over every transcript, each in its own temporary file;
    those paths in grep's output are replaced by the media paths."""
    with tempfile.TemporaryDirectory(prefix="oddjob-audio-grep-") as workdir:
        replacements: list[tuple[bytes, bytes]] = []
        for index, transcript in enumerate(transcripts):
            path = Path(workdir) / f"{index}.{output_format}"
            path.write_text(
                render_transcript(transcript.segments, output_format), encoding="utf-8"
            )
            replacements.append((os.fsencode(path), os.fsencode(transcript.media)))
        result = grep.run(
            [*grep_args, *(os.fsdecode(temp) for temp, _ in replacements)]
        )
    # Longest first, so no temporary path is replaced inside a longer one.
    replacements.sort(key=lambda pair: len(pair[0]), reverse=True)
    return GrepResult(
        returncode=result.returncode,
        stdout=replace_all(result.stdout, replacements),
        stderr=replace_all(result.stderr, replacements),
    )


def replace_all(output: bytes, replacements: Sequence[tuple[bytes, bytes]]) -> bytes:
    for old, new in replacements:
        output = output.replace(old, new)
    return output
