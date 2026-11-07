"""whisper.cpp (`whisper_cpp`) backend: unit tests against a fake whisper-cli, and an
integration test against the real one (GLADOS_TEST_WHISPER_CPP_* settings)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import pydantic
from support import drain, recorded_argv, require_settings, write_executable

from glados.lib.protocols import Transcriber, TranscriptSegment
from glados.plugins.whisper import (
    WhisperCppBackend,
    WhisperCppOptions,
    __glados_plugin__,
)

FAKE_WHISPER = """
import json
import sys
from pathlib import Path

args = sys.argv[1:]
Path(__file__).with_suffix(".argv").write_text(json.dumps(args))
if "--output-json" not in args:
    # Like the real whisper-cli: usage on stderr, exit 0, no output.
    print("error: unknown argument", file=sys.stderr)
    sys.exit(0)
prefix = args[args.index("--output-file") + 1]
print("whisper_print_progress_callback: progress =  50%", file=sys.stderr)
transcription = [
    {"offsets": {"from": 0, "to": 1500}, "text": " Hola mundo."},
    {"offsets": {"from": 1500, "to": 3250}, "text": " Adiós. "},
]
Path(prefix + ".json").write_text(json.dumps({"transcription": transcription}))
"""

FAILING_WHISPER = """
import sys

print("error: failed to read audio", file=sys.stderr)
sys.exit(3)
"""

SILENT_WHISPER = """
import sys
"""


class WhisperCppBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.model = self.workdir / "model.bin"
        self.model.touch()
        self.audio = self.workdir / "audio.wav"
        self.audio.touch()

    def backend(self, script: str) -> tuple[WhisperCppBackend, Path]:
        binary = write_executable(self.workdir, "whisper-cli", script)
        options = WhisperCppOptions(model=self.model, binary=str(binary))
        return WhisperCppBackend(options), binary

    def test_parses_segments_and_progress(self) -> None:
        backend, _ = self.backend(FAKE_WHISPER)

        events, result = drain(backend.transcribe(self.audio, language=None))

        self.assertEqual([event.completed for event in events], [50, 100])
        self.assertEqual(
            result,
            [
                TranscriptSegment(start=0.0, end=1.5, text="Hola mundo."),
                TranscriptSegment(start=1.5, end=3.25, text="Adiós."),
            ],
        )

    def test_invocation_and_cleanup(self) -> None:
        backend, binary = self.backend(FAKE_WHISPER)

        drain(backend.transcribe(self.audio, language="es"))

        argv = recorded_argv(binary)
        self.assertEqual(argv[0], "--print-progress")
        self.assertEqual(argv[argv.index("--file") + 1], str(self.audio))
        self.assertEqual(argv[argv.index("--model") + 1], str(self.model))
        self.assertEqual(argv[argv.index("--language") + 1], "es")
        json_output = Path(argv[argv.index("--output-file") + 1] + ".json")
        self.assertFalse(json_output.exists(), "temporary JSON output not removed")

    def test_autodetects_language_by_default(self) -> None:
        backend, binary = self.backend(FAKE_WHISPER)

        drain(backend.transcribe(self.audio, language=None))

        argv = recorded_argv(binary)
        self.assertEqual(argv[argv.index("--language") + 1], "auto")

    def test_failure_reports_stderr(self) -> None:
        backend, _ = self.backend(FAILING_WHISPER)

        with self.assertRaisesRegex(RuntimeError, "failed to read audio"):
            drain(backend.transcribe(self.audio, language=None))

    def test_missing_output_is_an_error(self) -> None:
        backend, _ = self.backend(SILENT_WHISPER)

        with self.assertRaisesRegex(RuntimeError, "expected whisper output"):
            drain(backend.transcribe(self.audio, language=None))

    def test_missing_model(self) -> None:
        backend, _ = self.backend(FAKE_WHISPER)
        self.model.unlink()

        with self.assertRaisesRegex(FileNotFoundError, "whisper.cpp model not found"):
            drain(backend.transcribe(self.audio, language=None))

    def test_missing_binary(self) -> None:
        options = WhisperCppOptions(model=self.model, binary=str(self.workdir / "nope"))

        with self.assertRaisesRegex(FileNotFoundError, "whisper binary not found"):
            drain(WhisperCppBackend(options).transcribe(self.audio, language=None))


class WhisperCppPluginTest(unittest.TestCase):
    def test_implements_transcribe(self) -> None:
        [(task, protocol, backend)] = __glados_plugin__("whisper_cpp", {})

        self.assertEqual((task, protocol), ("transcribe", Transcriber))
        self.assertIsInstance(backend, Transcriber)

    def test_expands_user_in_model(self) -> None:
        options = WhisperCppOptions.model_validate({"model": "~/model.bin"})

        self.assertEqual(options.model, Path.home() / "model.bin")

    def test_rejects_unknown_options(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            __glados_plugin__("whisper_cpp", {"modle": "typo.bin"})

    def test_rejects_unknown_backend(self) -> None:
        with self.assertRaisesRegex(ValueError, "provides no backend 'whisperx'"):
            __glados_plugin__("whisperx", {})


class WhisperCppIntegrationTest(unittest.TestCase):
    """Runs the real whisper-cli. Without GLADOS_TEST_WHISPER_CPP_AUDIO it
    transcribes a generated tone and only checks the call succeeds."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = require_settings("GLADOS_TEST_WHISPER_CPP_MODEL")
        if shutil.which("ffmpeg") is None:
            raise unittest.SkipTest("ffmpeg not on PATH")

    def test_transcribes(self) -> None:
        workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        wav = workdir / "audio.wav"
        source = self.settings.get("GLADOS_TEST_WHISPER_CPP_AUDIO")
        ffmpeg_input = (
            ["-i", str(Path(source).expanduser())]
            if source
            else ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
        )
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", *ffmpeg_input]
            + ["-ar", "16000", "-ac", "1", str(wav)],
            check=True,
        )
        options = WhisperCppOptions.model_validate(
            {
                "model": self.settings["GLADOS_TEST_WHISPER_CPP_MODEL"],
                "binary": self.settings.get(
                    "GLADOS_TEST_WHISPER_CPP_BINARY", "whisper-cli"
                ),
            }
        )

        _, segments = drain(
            WhisperCppBackend(options).transcribe(
                wav, language=self.settings.get("GLADOS_TEST_WHISPER_CPP_LANGUAGE")
            )
        )

        self.assertIsInstance(segments, list)
        expected = self.settings.get("GLADOS_TEST_WHISPER_CPP_EXPECT")
        if expected:
            transcript = " ".join(segment.text for segment in segments or [])
            self.assertIn(expected.lower(), transcript.lower())


if __name__ == "__main__":
    unittest.main()
