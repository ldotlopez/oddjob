"""Unit tests for audio-grep: argument splitting, the transcript cache and
grep over the transcripts. grep is the real one on PATH; transcription is
faked, and the command tests hit only a pre-filled cache."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner
from foundation.cache import MissingKeyError, UserCache
from support import NullReporter

from filejobs.inputs import media_type_filter
from filejobs.progress import ProgressEvent, ProgressStream
from glados.commands.audio_grep import audio_grep_cmd
from glados.lib.audio_grep import (
    TRANSCRIPT_TTL,
    CachedTranscripts,
    Transcript,
    TranscriptionSettings,
    decode_segments,
    encode_segments,
    grep_transcripts,
    split_command_line,
    transcript_key,
)
from glados.lib.grep import GrepRunner
from glados.lib.protocols import TranscriptSegment

SEGMENTS = [
    TranscriptSegment(start=1.0, end=2.5, text=" The Budget for Q3"),
    TranscriptSegment(start=3.0, end=4.0, text="something else"),
]
DEFAULTS = TranscriptionSettings(backend=None, model=None, language=None)
is_media = media_type_filter("audio/", "video/")


def make_tmp(test: unittest.TestCase) -> Path:
    return Path(test.enterContext(tempfile.TemporaryDirectory()))


class DictStore:
    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}

    def get(self, key: str) -> bytes:
        if key not in self.entries:
            raise MissingKeyError(key)
        return self.entries[key]

    def set(self, key: str, value: bytes) -> None:
        self.entries[key] = value


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(
        self, audio_path: Path, *, language: str | None
    ) -> ProgressStream[list[TranscriptSegment]]:
        self.calls.append((audio_path, language))
        yield ProgressEvent(completed=1, total=1, done=True, result=list(SEGMENTS))


class FakeExtractor:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def run(self, input_path: Path) -> ProgressStream[Path]:
        audio = self.directory / "extracted.wav"
        audio.write_bytes(b"wav")
        yield ProgressEvent(completed=1, total=1, done=True, result=audio)


class SplitCommandLineTests(unittest.TestCase):
    def test_media_files_and_directories_are_inputs(self) -> None:
        tmp = make_tmp(self)
        (tmp / "talk.mp4").write_bytes(b"video")
        (tmp / "patterns.txt").write_text("budget\n", encoding="utf-8")
        line = split_command_line(
            [
                "-i",
                "-f",
                str(tmp / "patterns.txt"),
                str(tmp / "talk.mp4"),
                "-A",
                "1",
                str(tmp),
                "missing.mp3",
            ],
            is_media,
        )
        self.assertEqual(line.paths, (tmp / "talk.mp4", tmp))
        self.assertEqual(
            line.grep_args,
            ("-i", "-f", str(tmp / "patterns.txt"), "-A", "1", "missing.mp3"),
        )


class TranscriptKeyTests(unittest.TestCase):
    def test_depends_on_content_mtime_and_settings_not_path(self) -> None:
        tmp = make_tmp(self)
        first, second = tmp / "a.mp3", tmp / "b.mp3"
        for path in (first, second):
            path.write_bytes(b"same audio")
            os.utime(path, ns=(1_000, 2_000))
        key = transcript_key(first, DEFAULTS)
        self.assertEqual(key, transcript_key(second, DEFAULTS))
        self.assertEqual(len(key), 64)
        self.assertNotIn("a.mp3", key)
        self.assertNotEqual(
            key,
            transcript_key(
                first, TranscriptionSettings(backend=None, model=None, language="es")
            ),
        )
        os.utime(second, ns=(1_000, 3_000))
        self.assertNotEqual(key, transcript_key(second, DEFAULTS))
        second.write_bytes(b"other audio")
        os.utime(second, ns=(1_000, 2_000))
        self.assertNotEqual(key, transcript_key(second, DEFAULTS))


class SegmentEncodingTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        self.assertEqual(decode_segments(encode_segments(SEGMENTS)), SEGMENTS)

    def test_malformed_values_are_value_errors(self) -> None:
        for value in (b"not json", b"{}", b'[["1", 2, "text"]]', b"[[1, 2]]"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_segments(value)


class CachedTranscriptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp(self)
        self.media = self.tmp / "talk.mp4"
        self.media.write_bytes(b"video")
        self.store = DictStore()
        self.transcriber = FakeTranscriber()
        self.built = 0

    def source(self, settings: TranscriptionSettings = DEFAULTS) -> CachedTranscripts:
        def make() -> FakeTranscriber:
            self.built += 1
            return self.transcriber

        return CachedTranscripts(
            self.store, make, settings, extractor=lambda: FakeExtractor(self.tmp)
        )

    def test_transcribes_once_then_reads_the_cache(self) -> None:
        settings = TranscriptionSettings(backend=None, model=None, language="en")
        self.assertEqual(
            self.source(settings).segments(self.media, NullReporter()), SEGMENTS
        )
        self.assertEqual(self.transcriber.calls, [(self.tmp / "extracted.wav", "en")])
        self.assertFalse((self.tmp / "extracted.wav").exists())

        self.assertEqual(
            self.source(settings).segments(self.media, NullReporter()), SEGMENTS
        )
        self.assertEqual((self.built, len(self.transcriber.calls)), (1, 1))

    def test_an_unreadable_entry_is_transcribed_again(self) -> None:
        self.store.set(transcript_key(self.media, DEFAULTS), b"garbage")
        with self.assertLogs("glados.lib.audio_grep", "WARNING"):
            self.assertEqual(
                self.source().segments(self.media, NullReporter()), SEGMENTS
            )
        self.assertEqual(len(self.transcriber.calls), 1)
        self.assertEqual(
            decode_segments(self.store.get(transcript_key(self.media, DEFAULTS))),
            SEGMENTS,
        )


class GrepTranscriptsTests(unittest.TestCase):
    def test_output_names_the_media_files(self) -> None:
        talks = [
            Transcript(Path(f"talks/{index}.mp4"), SEGMENTS) for index in range(12)
        ]
        result = grep_transcripts(GrepRunner(), ["-i", "budget"], talks, "lrc")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.decode(),
            "".join(
                f"talks/{index}.mp4:[00:01.00]The Budget for Q3\n"
                for index in range(12)
            ),
        )

    def test_grep_options_pass_through(self) -> None:
        talks = [Transcript(Path("a.mp3"), SEGMENTS)]
        counted = grep_transcripts(GrepRunner(), ["-c", "-v", "Budget"], talks, "txt")
        self.assertEqual((counted.returncode, counted.stdout), (0, b"1\n"))
        missing = grep_transcripts(GrepRunner(), ["absent"], talks, "txt")
        self.assertEqual((missing.returncode, missing.stdout), (1, b""))


class AudioGrepCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp(self)
        self.cache_home = self.tmp / "cache"
        self.enterContext(
            mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.cache_home)})
        )
        self.media_dir = self.tmp / "media"
        self.media_dir.mkdir()
        for name in ("meeting.mp4", "notes.m4a"):
            media = self.media_dir / name
            media.write_bytes(name.encode())
            with UserCache(
                app="glados",
                expiration_time=TRANSCRIPT_TTL,
                base_dir=self.cache_home / "glados" / "transcripts",
            ) as cache:
                cache.set(transcript_key(media, DEFAULTS), encode_segments(SEGMENTS))
        self.runner = CliRunner()

    def test_greps_cached_transcripts_and_writes_no_sidecar(self) -> None:
        result = self.runner.invoke(
            audio_grep_cmd, ["-i", "-n", "BUDGET", str(self.media_dir)]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"{self.media_dir / 'meeting.mp4'}:1:[00:01.00]The Budget for Q3\n"
            f"{self.media_dir / 'notes.m4a'}:1:[00:01.00]The Budget for Q3\n",
        )
        self.assertEqual(
            sorted(path.name for path in self.media_dir.iterdir()),
            ["meeting.mp4", "notes.m4a"],
        )

    def test_single_file_and_transcript_format(self) -> None:
        result = self.runner.invoke(
            audio_grep_cmd,
            ["--transcript-format", "txt", "else", str(self.media_dir / "notes.m4a")],
        )
        self.assertEqual((result.exit_code, result.stdout), (0, "something else\n"))

    def test_no_match_exits_1(self) -> None:
        result = self.runner.invoke(audio_grep_cmd, ["absent", str(self.media_dir)])
        self.assertEqual((result.exit_code, result.stdout), (1, ""))

    def test_needs_a_media_argument(self) -> None:
        result = self.runner.invoke(audio_grep_cmd, ["budget", "nothing-here.mp4"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("no audio/video file or directory", result.output)


if __name__ == "__main__":
    unittest.main()
