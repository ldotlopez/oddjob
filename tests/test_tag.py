"""tag: content kind, model reply parsing, hashtag normalization, the Tagger's
routing and cache with fake backends, and the command end to end through
the llm backend's fake executable."""

import json
import logging
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from click.testing import CliRunner, Result
from support import NullReporter, recorded_argv, write_executable
from test_describe import DictStore

from filejobs.progress import ProgressEvent, ProgressStream
from filejobs.runners import CliArgs
from oddjob.commands import tag
from oddjob.core.config import Prompts
from oddjob.lib.protocols import TranscriptSegment
from oddjob.lib.tag import (
    TEXT_LIMIT,
    ContentKind,
    Tagger,
    TagResult,
    kind_of,
    normalize_hashtags,
    parse_reply,
)
from oddjob.lib.transcribe import AudioExtractor

REPLY = '{"description": "una nota breve", "hashtags": ["Notas", "#Prueba"]}'

# Records argv and stdin, then replies with REPLY, or with prose when the
# user message contains "unparseable".
JSON_LLM = f"""
import json
import sys
from pathlib import Path

Path(__file__).with_suffix(".argv").write_text(json.dumps(sys.argv[1:]))
user = sys.stdin.buffer.read().decode("utf-8")
Path(__file__).with_suffix(".stdin").write_text(user, encoding="utf-8")
print("no JSON here" if "unparseable" in user else {REPLY!r})
"""


def reply_stream(reply: str) -> ProgressStream[str]:
    yield ProgressEvent(completed=len(reply), total=None)
    yield ProgressEvent(completed=len(reply), total=len(reply), done=True, result=reply)


class FakeRewriter:
    def __init__(self, reply: str = REPLY) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def rewrite(self, text: str, *, prompt: str) -> ProgressStream[str]:
        self.calls.append((text, prompt))
        return reply_stream(self.reply)


class FakeDescriber:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str]] = []

    def describe(self, image: Path, *, prompt: str) -> ProgressStream[str]:
        self.calls.append((image, prompt))
        return reply_stream(REPLY)


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def transcribe(
        self, audio_path: Path, *, language: str | None
    ) -> ProgressStream[list[TranscriptSegment]]:
        self.calls.append(audio_path)
        segments = [TranscriptSegment(0.0, 1.0, " receta de paella ")]
        yield ProgressEvent(completed=1, total=1, done=True, result=segments)


class FakeBackends:
    """TaskBackends over the fakes, counting what gets built."""

    def __init__(self, rewriter: FakeRewriter | None = None) -> None:
        self.rewriter_fake = rewriter or FakeRewriter()
        self.describer_fake = FakeDescriber()
        self.transcriber_fake = FakeTranscriber()
        self.built: list[str] = []
        self.options: dict[str, dict[str, Any]] = {}

    def rewriter(self) -> FakeRewriter:
        self.built.append("rewrite")
        return self.rewriter_fake

    def describer(self) -> FakeDescriber:
        self.built.append("describe")
        return self.describer_fake

    def transcriber(self) -> FakeTranscriber:
        self.built.append("transcribe")
        return self.transcriber_fake

    def settings(self, task: str) -> tuple[str, Mapping[str, Any]]:
        return "fake", self.options.get(task, {})


class FakeExtractor:
    """A ProgressStep[Path] standing in for AudioExtractor."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.inputs: list[Path] = []

    def run(self, input_path: Path) -> ProgressStream[Path]:
        self.inputs.append(input_path)
        audio = self.workdir / "extracted.wav"
        audio.write_bytes(b"wav")
        yield ProgressEvent(completed=1, total=1, done=True, result=audio)


class KindTests(unittest.TestCase):
    def test_kind_comes_from_the_file_name(self) -> None:
        cases = {
            "a.jpg": ContentKind.IMAGE,
            "a.mp3": ContentKind.AUDIO,
            "a.ogg": ContentKind.AUDIO,
            "a.mp4": ContentKind.VIDEO,
            "a.3gp": ContentKind.VIDEO,
            "a.txt": ContentKind.TEXT,
            "a.md": ContentKind.TEXT,
            "a.pdf": ContentKind.DOCUMENT,
            "README": ContentKind.DOCUMENT,
        }
        for name, kind in cases.items():
            with self.subTest(name=name):
                self.assertEqual(kind_of(Path(name)), kind)

    def test_link_is_never_detected(self) -> None:
        self.assertEqual(ContentKind("link"), ContentKind.LINK)
        self.assertNotIn(
            ContentKind.LINK, {kind_of(Path(f"a.{ext}")) for ext in ("html", "url")}
        )


class ReplyTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        result = parse_reply(REPLY, ContentKind.TEXT)
        self.assertEqual(
            result, TagResult(ContentKind.TEXT, "una nota breve", ("#notas", "#prueba"))
        )

    def test_json_wrapped_in_a_fence_or_prose(self) -> None:
        for reply in (
            f"```json\n{REPLY}\n```",
            f"Here it is:\n{REPLY}\nHope it helps.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    parse_reply(reply, ContentKind.IMAGE).description, "una nota breve"
                )

    def test_invalid_replies_raise_value_error(self) -> None:
        for reply in (
            "no JSON here",
            "{not json}",
            '{"description": "x"}',
            '{"hashtags": ["a"]}',
            '{"description": "x", "hashtags": "a b"}',
            '{"description": 3, "hashtags": []}',
            '{"description": "  ", "hashtags": ["a"]}',
        ):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                parse_reply(reply, ContentKind.TEXT)


class HashtagTests(unittest.TestCase):
    def test_lowercase_keeps_accents_and_drops_spaces_and_punctuation(self) -> None:
        self.assertEqual(
            normalize_hashtags(["#Código Fuente", "¡Cocina!", "año_2024"]),
            ("#códigofuente", "#cocina", "#año_2024"),
        )

    def test_duplicates_and_empty_tags_are_dropped(self) -> None:
        self.assertEqual(
            normalize_hashtags(["cocina", "#Cocina", "#", " ", "viajes"]),
            ("#cocina", "#viajes"),
        )

    def test_at_most_three(self) -> None:
        self.assertEqual(normalize_hashtags(["a", "b", "c", "d"]), ("#a", "#b", "#c"))


class TaggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.backends = FakeBackends()
        self.extractor = FakeExtractor(self.tmp)
        self.store = DictStore()

    def tagger(
        self, *, prompt: str = "P", max_duration: float | None = 60, cache: bool = True
    ) -> Tagger:
        return Tagger(
            self.backends,
            prompt,
            store=self.store if cache else None,
            max_duration=max_duration,
            extractor=lambda: self.extractor,
        )

    def file(self, name: str, content: bytes = b"bytes") -> Path:
        path = self.tmp / name
        path.write_bytes(content)
        return path

    def test_text_goes_to_rewrite(self) -> None:
        result = self.tagger().tag_text("hola mundo", None, NullReporter())
        self.assertEqual(result.kind, ContentKind.TEXT)
        self.assertEqual(result.hashtags, ("#notas", "#prueba"))
        [(user, prompt)] = self.backends.rewriter_fake.calls
        self.assertIn("hola mundo", user)
        self.assertEqual(prompt, "P")
        self.assertEqual(self.backends.built, ["rewrite"])

    def test_context_joins_the_user_message(self) -> None:
        self.tagger().tag_text("hola", "pie de foto", NullReporter())
        [(user, _)] = self.backends.rewriter_fake.calls
        self.assertIn("pie de foto", user)

    def test_image_goes_to_describe_in_one_call_with_the_context(self) -> None:
        image = self.file("gato.jpg")
        result = self.tagger().tag_file(image, "mi gato", NullReporter())
        self.assertEqual(result.kind, ContentKind.IMAGE)
        [(path, prompt)] = self.backends.describer_fake.calls
        self.assertEqual(path, image)
        self.assertTrue(prompt.startswith("P"))
        self.assertIn("mi gato", prompt)
        self.assertEqual(self.backends.built, ["describe"])

    def test_audio_is_extracted_transcribed_then_rewritten(self) -> None:
        audio = self.file("nota.ogg")
        result = self.tagger().tag_file(audio, None, NullReporter())
        self.assertEqual(result.kind, ContentKind.AUDIO)
        self.assertEqual(self.extractor.inputs, [audio])
        self.assertEqual(
            self.backends.transcriber_fake.calls, [self.tmp / "extracted.wav"]
        )
        [(user, _)] = self.backends.rewriter_fake.calls
        self.assertIn("receta de paella", user)
        self.assertIn("nota.ogg", user)
        self.assertFalse((self.tmp / "extracted.wav").exists())

    def test_video_takes_the_audio_route(self) -> None:
        result = self.tagger().tag_file(self.file("clip.mp4"), None, NullReporter())
        self.assertEqual(result.kind, ContentKind.VIDEO)
        self.assertEqual(len(self.backends.transcriber_fake.calls), 1)

    def test_text_file_content_is_sent_up_to_the_limit(self) -> None:
        body = "x" * (TEXT_LIMIT + 100)
        self.tagger().tag_file(self.file("a.txt", body.encode()), None, NullReporter())
        [(user, _)] = self.backends.rewriter_fake.calls
        self.assertIn("x" * TEXT_LIMIT, user)
        self.assertNotIn("x" * (TEXT_LIMIT + 1), user)

    def test_document_sends_name_and_media_type_only(self) -> None:
        pdf = self.file("factura.pdf", b"%PDF secret body")
        result = self.tagger().tag_file(pdf, None, NullReporter())
        self.assertEqual(result.kind, ContentKind.DOCUMENT)
        [(user, _)] = self.backends.rewriter_fake.calls
        self.assertIn("factura.pdf", user)
        self.assertIn("application/pdf", user)
        self.assertNotIn("secret body", user)

    def test_an_invalid_reply_fails_and_is_not_cached(self) -> None:
        self.backends.rewriter_fake.reply = "no JSON here"
        with self.assertRaises(ValueError):
            self.tagger().tag_text("hola", None, NullReporter())
        self.assertEqual(self.store.entries, {})

    def test_second_call_is_served_from_the_cache_without_backends(self) -> None:
        audio = self.file("nota.ogg")
        first = self.tagger().tag_file(audio, None, NullReporter())
        self.backends.built.clear()
        second = self.tagger().tag_file(audio, None, NullReporter())
        self.assertEqual(second, first)
        self.assertEqual(self.backends.built, [])
        self.assertEqual(self.extractor.inputs, [audio])

    def test_each_input_to_the_reply_makes_a_new_entry(self) -> None:
        audio = self.file("nota.ogg")
        self.tagger().tag_file(audio, None, NullReporter())
        variants = [
            lambda: self.tagger().tag_file(audio, "otro contexto", NullReporter()),
            lambda: self.tagger(prompt="Q").tag_file(audio, None, NullReporter()),
            lambda: self.tagger(max_duration=120).tag_file(audio, None, NullReporter()),
            lambda: self.tagger(max_duration=None).tag_file(
                audio, None, NullReporter()
            ),
        ]
        for count, variant in enumerate(variants, start=2):
            variant()
            self.assertEqual(len(self.store.entries), count)
        self.backends.options["transcribe"] = {"model": "other"}
        self.tagger().tag_file(audio, None, NullReporter())
        self.assertEqual(len(self.store.entries), len(variants) + 2)

    def test_secret_options_do_not_change_the_key(self) -> None:
        self.tagger().tag_text("hola", None, NullReporter())
        self.backends.options["rewrite"] = {"api_key": "s3cret"}
        self.tagger().tag_text("hola", None, NullReporter())
        self.assertEqual(len(self.store.entries), 1)

    def test_without_a_store_every_call_reaches_the_backend(self) -> None:
        for _ in range(2):
            self.tagger(cache=False).tag_text("hola", None, NullReporter())
        self.assertEqual(len(self.backends.rewriter_fake.calls), 2)


class FakeRunner:
    def __init__(self) -> None:
        self.args: CliArgs = []
        self.duration: float | None = None

    def probe_duration(self, input_path: Path) -> float | None:
        return 600.0

    def run(self, args: CliArgs, duration: float | None = None) -> ProgressStream:
        self.args, self.duration = args, duration
        yield ProgressEvent(completed=1, total=1, done=True)


class AudioExtractorDurationTests(unittest.TestCase):
    def extract(self, max_duration: float | None) -> FakeRunner:
        runner = FakeRunner()
        events = list(
            AudioExtractor(runner, max_duration=max_duration).run(Path("v.mp4"))
        )
        events[-1].result.unlink(missing_ok=True)
        return runner

    def test_max_duration_cuts_the_audio(self) -> None:
        runner = self.extract(60)
        self.assertEqual(runner.args[runner.args.index("-t") + 1], "60")
        self.assertEqual(runner.duration, 60)

    def test_no_limit_extracts_everything(self) -> None:
        runner = self.extract(None)
        self.assertNotIn("-t", runner.args)
        self.assertEqual(runner.duration, 600.0)


class PromptTests(unittest.TestCase):
    def test_default_prompt_asks_for_json_and_appends_the_language(self) -> None:
        prompt = Prompts().render_tag("Spanish")
        self.assertIn("JSON", prompt)
        self.assertTrue(prompt.endswith(" Reply in Spanish."))
        self.assertNotIn("Reply in", Prompts().render_tag(None))

    def test_tag_prompt_takes_no_placeholder(self) -> None:
        with self.assertRaises(ValueError):
            Prompts(tag="Tag it {instructions}")


class TagCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runner = CliRunner()
        for name in ("filejobs", "oddjob"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)
        self.llm = write_executable(self.tmp, "llm", JSON_LLM)
        config = self.tmp / "config" / "oddjob"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(
            '[tasks]\nrewrite = "llm"\ndescribe = "llm"\n\n'
            f'[backends.llm]\nbinary = "{self.llm}"\n',
            encoding="utf-8",
        )
        self.env = {
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
            "LC_ALL": "C",
        }

    def invoke(self, args: list[str], stdin: str | None = None) -> Result:
        return self.runner.invoke(tag.tag_cmd, args, input=stdin, env=self.env)

    def sent_user_message(self) -> str:
        return self.llm.with_suffix(".stdin").read_text(encoding="utf-8")

    def sent_system_prompt(self) -> str:
        argv = recorded_argv(self.llm)
        return argv[argv.index("-s") + 1]

    def test_text_option_prints_one_line(self) -> None:
        result = self.invoke(["--text", "hola mundo"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "text: text · una nota breve #notas #prueba\n")
        self.assertIn("hola mundo", self.sent_user_message())

    def test_stdin_is_read_when_piped(self) -> None:
        result = self.invoke([], stdin="desde la tubería")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "stdin: text · una nota breve #notas #prueba\n")
        self.assertIn("desde la tubería", self.sent_user_message())

    def test_files_are_tagged_by_path(self) -> None:
        note = self.tmp / "nota.txt"
        note.write_text("contenido", encoding="utf-8")
        image = self.tmp / "gato.jpg"
        image.write_bytes(b"jpeg")
        result = self.invoke([str(note), str(image)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"{note}: text · una nota breve #notas #prueba\n"
            f"{image}: image · una nota breve #notas #prueba\n",
        )
        self.assertEqual(recorded_argv(self.llm)[-2:], ["-a", str(image)])

    def test_json_prints_one_object_per_line(self) -> None:
        result = self.invoke(["--json", "--text", "hola"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "path": None,
                "type": "text",
                "description": "una nota breve",
                "hashtags": ["#notas", "#prueba"],
            },
        )

    def test_json_names_the_file(self) -> None:
        note = self.tmp / "nota.txt"
        note.write_text("contenido", encoding="utf-8")
        result = self.invoke(["--json", str(note)])
        self.assertEqual(json.loads(result.stdout)["path"], str(note))

    def test_type_forces_the_label_only(self) -> None:
        note = self.tmp / "pagina.txt"
        note.write_text("texto de la web", encoding="utf-8")
        result = self.invoke(["--type", "link", "--context", "titulo", str(note)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout, f"{note}: link · una nota breve #notas #prueba\n"
        )
        self.assertIn("texto de la web", self.sent_user_message())
        self.assertIn("titulo", self.sent_user_message())

    def test_language_is_added_to_the_prompt(self) -> None:
        result = self.invoke(["-l", "fr", "--text", "hola"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.sent_system_prompt().endswith(" Reply in French."))

    def test_one_failed_input_does_not_stop_the_rest(self) -> None:
        good = self.tmp / "a.txt"
        good.write_text("bien", encoding="utf-8")
        bad = self.tmp / "b.txt"
        bad.write_text("unparseable", encoding="utf-8")
        result = self.invoke([str(good), str(bad)])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(
            result.stdout, f"{good}: text · una nota breve #notas #prueba\n"
        )
        self.assertIn("1 done, 1 failed", result.stderr)

    def test_second_run_is_served_from_the_cache(self) -> None:
        first = self.invoke(["--text", "hola"])
        self.llm.unlink()
        second = self.invoke(["--text", "hola"])
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(second.stdout, first.stdout)

    def test_no_cache_always_asks_the_model(self) -> None:
        self.invoke(["--no-cache", "--text", "hola"])
        self.llm.unlink()
        self.assertNotEqual(self.invoke(["--no-cache", "--text", "hola"]).exit_code, 0)

    def test_usage_errors(self) -> None:
        note = self.tmp / "a.txt"
        note.write_text("x", encoding="utf-8")
        cases = [
            ["--max-duration", "30", "--full-audio", str(note)],
            ["--text", "hola", str(note)],
            ["--text", "  "],
            ["-", str(note)],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.invoke(args)
                self.assertEqual(result.exit_code, 2, result.output)


if __name__ == "__main__":
    unittest.main()
