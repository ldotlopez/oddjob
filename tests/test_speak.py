"""speak: source selection, the step, and the command end to end through the
piper backend's fake executable."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner, Result
from support import NullReporter, recorded_argv, write_executable
from test_piper import FAKE_PIPER

from filejobs.pipeline import Job, suffix_destination
from filejobs.progress import ProgressEvent, ProgressStream
from glados.commands import speak
from glados.lib.speak import (
    FileSource,
    SourceError,
    SpeakStep,
    TextSource,
    choose_source,
    describe_text,
)

OUT = Path("out.wav")


class FakeSpeaker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def speak(self, text: str, *, speaker: int | None) -> ProgressStream[Path]:
        self.calls.append((text, speaker))
        audio = Path(tempfile.mkstemp(prefix="fake-speak-", suffix=".wav")[1])
        audio.write_bytes(b"RIFFfake")
        yield ProgressEvent(completed=1, total=1, done=True, result=audio)


class ChooseSourceTests(unittest.TestCase):
    def choose(
        self,
        paths: tuple[Path, ...] = (),
        text: str | None = None,
        output: Path | None = OUT,
        terminal: bool = False,
    ) -> FileSource | TextSource:
        return choose_source(paths, text, output, stdin_is_terminal=terminal)

    def test_paths_are_files_and_need_no_output(self) -> None:
        paths = (Path("a.txt"), Path("b.txt"))
        self.assertEqual(self.choose(paths, output=None), FileSource(paths))

    def test_paths_ignore_a_pipe(self) -> None:
        paths = (Path("a.txt"),)
        self.assertEqual(self.choose(paths, terminal=False), FileSource(paths))

    def test_text_option(self) -> None:
        self.assertEqual(self.choose(text="Hi"), TextSource("Hi"))

    def test_dash_reads_stdin_even_on_a_terminal(self) -> None:
        self.assertEqual(self.choose((Path("-"),), terminal=True), TextSource(None))

    def test_pipe_without_paths_reads_stdin(self) -> None:
        self.assertEqual(self.choose(), TextSource(None))

    def test_terminal_without_a_source_is_an_error(self) -> None:
        with self.assertRaisesRegex(SourceError, "no input"):
            self.choose(terminal=True)

    def test_text_with_paths_is_an_error(self) -> None:
        with self.assertRaisesRegex(SourceError, "either"):
            self.choose((Path("a.txt"),), text="Hi")

    def test_dash_with_other_paths_or_text_is_an_error(self) -> None:
        with self.assertRaisesRegex(SourceError, "alone"):
            self.choose((Path("-"), Path("a.txt")))
        with self.assertRaisesRegex(SourceError, "alone"):
            self.choose((Path("-"),), text="Hi")

    def test_text_sources_need_an_output(self) -> None:
        for kwargs in ({"text": "Hi"}, {"paths": (Path("-"),)}, {}):
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(SourceError, "-o/--output"),
            ):
                self.choose(output=None, **kwargs)

    def test_blank_text_option_is_an_error(self) -> None:
        with self.assertRaisesRegex(SourceError, "empty"):
            self.choose(text="  \n")


class DescribeTextTests(unittest.TestCase):
    def test_short_text_is_quoted(self) -> None:
        self.assertEqual(describe_text("Hello there"), '"Hello there"')

    def test_whitespace_is_collapsed_and_long_text_cut(self) -> None:
        shown = describe_text("word  \n" * 30)
        self.assertTrue(shown.endswith('..."'))
        self.assertNotIn("\n", shown)
        self.assertLess(len(shown), 50)


class SpeakStepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def job(self, speaker: FakeSpeaker, number: int | None = None) -> Job:
        return Job(
            steps=[(SpeakStep(speaker, number), "Speaking")],
            dest_fn=suffix_destination("wav"),
        )

    def test_writes_a_wav_next_to_the_text(self) -> None:
        note = self.tmp / "note.txt"
        note.write_text("Hello there", encoding="utf-8")
        speaker = FakeSpeaker()

        dest = self.job(speaker, 2).run(note, NullReporter())

        self.assertEqual(dest, self.tmp / "note.wav")
        self.assertEqual(dest.read_bytes(), b"RIFFfake")
        self.assertEqual(speaker.calls, [("Hello there", 2)])

    def test_blank_text_is_an_error(self) -> None:
        note = self.tmp / "note.txt"
        note.write_text(" \n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "no text to speak"):
            self.job(FakeSpeaker()).run(note, NullReporter())
        self.assertFalse((self.tmp / "note.wav").exists())


class SpeakCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.note = self.tmp / "note.txt"
        self.note.write_text("Hello from a file", encoding="utf-8")
        self.runner = CliRunner()
        for name in ("filejobs", "glados"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def with_fake_piper(self) -> tuple[Path, dict[str, str | None]]:
        """A fake piper, a voice file and the environment whose config
        selects them."""
        piper = write_executable(self.tmp, "piper", FAKE_PIPER)
        voice = self.tmp / "voice.onnx"
        voice.touch()
        config = self.tmp / "config" / "glados"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(
            f'[tasks]\nspeak = "piper"\n\n[backends.piper]\n'
            f'binary = "{piper}"\nmodel = "{voice}"\n',
            encoding="utf-8",
        )
        return piper, {
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "GLADOS_SPEAK_BACKEND": None,
        }

    def invoke(
        self,
        args: list[str],
        input: str | None = None,
        env: dict[str, str | None] | None = None,
    ) -> Result:
        return self.runner.invoke(speak.speak_cmd, args, input=input, env=env)

    def test_dry_run_on_files_needs_no_backend_and_skips_outputs(self) -> None:
        env = {"XDG_CONFIG_HOME": str(self.tmp / "config")}
        (self.tmp / "image.png").write_bytes(b"png")

        result = self.invoke(["-n", str(self.tmp)], env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, f"{self.note} -> {self.tmp / 'note.wav'}\n")

    def test_dry_run_on_text_and_stdin(self) -> None:
        out = str(self.tmp / "out.wav")

        text = self.invoke(["-n", "--text", "Hello there", "-o", out])
        stdin = self.invoke(["-n", "-", "-o", out], input="not consumed")

        self.assertEqual(text.stdout, f'"Hello there" -> {out}\n', text.output)
        self.assertEqual(stdin.stdout, f"- -> {out}\n", stdin.output)

    def test_file_is_spoken_silently(self) -> None:
        piper, env = self.with_fake_piper()

        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.invoke(["-v", str(self.note)], env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        destination = self.tmp / "note.wav"
        self.assertIn(f"wrote {destination}", [r.getMessage() for r in logs.records])
        self.assertEqual(destination.read_bytes(), b"RIFFfake")
        self.assertEqual(
            piper.with_suffix(".stdin").read_text(encoding="utf-8"),
            "Hello from a file",
        )

    def test_text_option(self) -> None:
        piper, env = self.with_fake_piper()
        out = self.tmp / "hello.wav"

        result = self.invoke(["--text", "Hello there", "-o", str(out)], env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        self.assertEqual(out.read_bytes(), b"RIFFfake")
        self.assertEqual(
            piper.with_suffix(".stdin").read_text(encoding="utf-8"), "Hello there"
        )

    def test_dash_and_a_pipe_read_stdin(self) -> None:
        piper, env = self.with_fake_piper()
        for args in (["-", "-o"], ["-o"]):
            with self.subTest(args=args):
                out = self.tmp / f"{len(args)}.wav"
                result = self.invoke([*args[:-1], "-o", str(out)], "piped", env)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(out.read_bytes(), b"RIFFfake")
                self.assertEqual(
                    piper.with_suffix(".stdin").read_text(encoding="utf-8"), "piped"
                )

    def test_a_pipe_is_ignored_when_a_path_is_given(self) -> None:
        piper, env = self.with_fake_piper()

        result = self.invoke([str(self.note)], input="ignored", env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            piper.with_suffix(".stdin").read_text(encoding="utf-8"),
            "Hello from a file",
        )

    def test_speaker_option_reaches_piper(self) -> None:
        piper, env = self.with_fake_piper()

        result = self.invoke(["--speaker", "3", str(self.note)], env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        argv = recorded_argv(piper)
        self.assertEqual(argv[argv.index("--speaker") + 1], "3")

    def test_model_option_selects_the_voice(self) -> None:
        piper, env = self.with_fake_piper()
        other = self.tmp / "other.onnx"
        other.touch()

        result = self.invoke(["-m", str(other), str(self.note)], env=env)

        self.assertEqual(result.exit_code, 0, result.output)
        argv = recorded_argv(piper)
        self.assertEqual(argv[argv.index("--model") + 1], str(other))

    def test_usage_errors_exit_2(self) -> None:
        out = str(self.tmp / "out.wav")
        note = str(self.note)
        other = self.tmp / "other.txt"
        other.write_text("more", encoding="utf-8")
        cases = {
            "text without -o": ["--text", "Hi"],
            "stdin without -o": ["-"],
            "text with a path": ["--text", "Hi", "-o", out, note],
            "dash with a path": ["-", note, "-o", out],
            "empty text": ["--text", " ", "-o", out],
            "-o with two files": ["-o", out, note, str(other)],
        }
        for name, args in cases.items():
            with self.subTest(name):
                result = self.invoke(args, input="")
                self.assertEqual(result.exit_code, 2, result.output)

    def test_blank_stdin_fails_that_input(self) -> None:
        _, env = self.with_fake_piper()
        out = self.tmp / "out.wav"

        result = self.invoke(["-o", str(out)], input="  \n", env=env)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("0 done, 1 failed", result.output)
        self.assertFalse(out.exists())

    def test_one_failing_input_does_not_stop_the_rest(self) -> None:
        _, env = self.with_fake_piper()
        blank = self.tmp / "blank.txt"
        blank.write_text("\n", encoding="utf-8")

        result = self.invoke([str(blank), str(self.note)], env=env)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("1 done, 1 failed", result.output)
        self.assertTrue((self.tmp / "note.wav").is_file())

    def test_existing_destination_needs_overwrite(self) -> None:
        _, env = self.with_fake_piper()
        existing = self.tmp / "note.wav"
        existing.write_bytes(b"old")

        refused = self.invoke([str(self.note)], env=env)
        allowed = self.invoke(["-y", str(self.note)], env=env)

        self.assertEqual(refused.exit_code, 1, refused.output)
        self.assertEqual(allowed.exit_code, 0, allowed.output)
        self.assertEqual(existing.read_bytes(), b"RIFFfake")


if __name__ == "__main__":
    unittest.main()
