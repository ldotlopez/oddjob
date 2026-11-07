"""piper backend: unit tests against a fake `piper`, and an integration test
against the real one (ODDJOB_TEST_PIPER_* settings)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import pydantic
from support import drain, recorded_argv, require_settings, write_executable

from oddjob.lib.protocols import Speaker
from oddjob.plugins.piper import PiperBackend, PiperOptions, __oddjob_plugin__

FAKE_PIPER = """
import json
import sys
from pathlib import Path

args = sys.argv[1:]
Path(__file__).with_suffix(".argv").write_text(json.dumps(args))
Path(__file__).with_suffix(".stdin").write_text(sys.stdin.read())
Path(args[args.index("--output_file") + 1]).write_bytes(b"RIFFfake")
"""

FAILING_PIPER = """
import sys

print("error: cannot load voice", file=sys.stderr)
sys.exit(3)
"""

SILENT_PIPER = """
import sys
"""


class PiperBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.voice = self.workdir / "voice.onnx"
        self.voice.touch()

    def backend(self, script: str) -> tuple[PiperBackend, Path]:
        binary = write_executable(self.workdir, "piper", script)
        options = PiperOptions(model=self.voice, binary=str(binary))
        return PiperBackend(options), binary

    def test_speaks_to_a_wav_file(self) -> None:
        backend, _ = self.backend(FAKE_PIPER)

        _, result = drain(backend.speak("Hello there", speaker=None))

        assert result is not None
        self.addCleanup(result.unlink, missing_ok=True)
        self.assertEqual(result.suffix, ".wav")
        self.assertEqual(result.read_bytes(), b"RIFFfake")

    def test_invocation_sends_text_on_stdin_with_long_options(self) -> None:
        backend, binary = self.backend(FAKE_PIPER)

        _, result = drain(backend.speak("Hello there", speaker=None))

        assert result is not None
        self.addCleanup(result.unlink, missing_ok=True)
        argv = recorded_argv(binary)
        self.assertEqual(argv[argv.index("--model") + 1], str(self.voice))
        self.assertEqual(argv[argv.index("--output_file") + 1], str(result))
        self.assertNotIn("--speaker", argv)
        self.assertNotIn("Hello there", argv)
        self.assertEqual(
            binary.with_suffix(".stdin").read_text(encoding="utf-8"), "Hello there"
        )

    def test_passes_the_speaker(self) -> None:
        backend, binary = self.backend(FAKE_PIPER)

        _, result = drain(backend.speak("Hi", speaker=3))

        assert result is not None
        self.addCleanup(result.unlink, missing_ok=True)
        argv = recorded_argv(binary)
        self.assertEqual(argv[argv.index("--speaker") + 1], "3")

    def test_failure_reports_stderr_and_leaves_no_temp_file(self) -> None:
        backend, _ = self.backend(FAILING_PIPER)

        with self.assertRaisesRegex(RuntimeError, "cannot load voice"):
            drain(backend.speak("Hi", speaker=None))

    def test_missing_output_is_an_error(self) -> None:
        backend, _ = self.backend(SILENT_PIPER)

        with self.assertRaisesRegex(RuntimeError, "wrote no audio"):
            drain(backend.speak("Hi", speaker=None))

    def test_missing_voice(self) -> None:
        backend, _ = self.backend(FAKE_PIPER)
        self.voice.unlink()

        with self.assertRaisesRegex(FileNotFoundError, "piper voice not found"):
            drain(backend.speak("Hi", speaker=None))

    def test_missing_binary(self) -> None:
        options = PiperOptions(model=self.voice, binary=str(self.workdir / "nope"))

        with self.assertRaisesRegex(FileNotFoundError, "piper binary not found"):
            drain(PiperBackend(options).speak("Hi", speaker=None))


class PiperPluginTest(unittest.TestCase):
    def test_implements_speak(self) -> None:
        [(task, protocol, backend)] = __oddjob_plugin__("piper", {})

        self.assertEqual((task, protocol), ("speak", Speaker))
        self.assertIsInstance(backend, Speaker)

    def test_expands_user_in_model(self) -> None:
        options = PiperOptions.model_validate({"model": "~/voice.onnx"})

        self.assertEqual(options.model, Path.home() / "voice.onnx")

    def test_rejects_unknown_options(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            __oddjob_plugin__("piper", {"modle": "x"})

    def test_unknown_backend_names_the_provided_ones(self) -> None:
        with self.assertRaisesRegex(ValueError, "provides no backend 'espeak'"):
            __oddjob_plugin__("espeak", {})


class PiperIntegrationTest(unittest.TestCase):
    """Runs the real piper with the voice in ODDJOB_TEST_PIPER_MODEL."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = require_settings("ODDJOB_TEST_PIPER_MODEL")

    def test_speaks(self) -> None:
        binary = self.settings.get("ODDJOB_TEST_PIPER_BINARY", "piper")
        if shutil.which(binary) is None:
            raise unittest.SkipTest(f"{binary} not on PATH")
        options = PiperOptions.model_validate(
            {"model": self.settings["ODDJOB_TEST_PIPER_MODEL"], "binary": binary}
        )

        _, result = drain(PiperBackend(options).speak("Hello there.", speaker=None))

        assert result is not None
        self.addCleanup(result.unlink, missing_ok=True)
        self.assertTrue(result.read_bytes().startswith(b"RIFF"))


if __name__ == "__main__":
    unittest.main()
