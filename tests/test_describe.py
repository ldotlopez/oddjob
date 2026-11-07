"""describe: the step, its prompt, and the command end to end through the llm
backend's fake executable."""

import locale
import logging
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner
from foundation.cache import CacheMissError
from support import NullReporter, recorded_argv, write_executable
from test_llm import ECHO_LLM

from filejobs.pipeline import Job, suffix_destination
from filejobs.progress import ProgressEvent, ProgressStream
from oddjob.commands import describe
from oddjob.core.config import Prompts
from oddjob.lib.describe import (
    DESCRIPTION_EXTENSION,
    CachedDescriber,
    DescribeStep,
    DescriptionSettings,
    describe_image,
)
from oddjob.lib.language import language_name, locale_language


class FakeDescriber:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str]] = []

    def describe(self, image: Path, *, prompt: str) -> ProgressStream[str]:
        self.calls.append((image, prompt))
        yield ProgressEvent(completed=3, total=None)
        yield ProgressEvent(completed=3, total=3, done=True, result="a cat")


class DictStore:
    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}

    def get(self, key: str) -> bytes:
        try:
            return self.entries[key]
        except KeyError:
            raise CacheMissError(key) from None

    def set(self, key: str, value: bytes) -> None:
        self.entries[key] = value


class CachedDescriberTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.image = tmp / "cat.jpg"
        self.image.write_bytes(b"jpeg")
        self.store = DictStore()
        self.describer = FakeDescriber()
        self.built = 0

    def cached(self, model: str = "m", **options: str) -> CachedDescriber:
        def make() -> FakeDescriber:
            self.built += 1
            return self.describer

        return CachedDescriber(
            self.store, make, DescriptionSettings("llm", {"model": model, **options})
        )

    def describe(self, cached: CachedDescriber, prompt: str = "p") -> str:
        return describe_image(cached, prompt, self.image, NullReporter())

    def test_describes_once_then_reads_the_cache(self) -> None:
        self.assertEqual(self.describe(self.cached()), "a cat")
        self.assertEqual(self.describe(self.cached()), "a cat")
        self.assertEqual((self.built, len(self.describer.calls)), (1, 1))
        (key,) = self.store.entries
        self.assertTrue(key.startswith("describe/"))
        self.assertNotIn("cat.jpg", key)

    def test_the_backend_is_not_built_on_a_hit(self) -> None:
        self.describe(self.cached())
        self.built = 0
        self.describe(self.cached())
        self.assertEqual(self.built, 0)

    def test_prompt_model_and_content_each_make_a_new_entry(self) -> None:
        self.describe(self.cached())
        self.describe(self.cached(), prompt="other prompt")
        self.describe(self.cached(model="vision"))
        self.image.write_bytes(b"other jpeg")
        self.describe(self.cached())
        self.assertEqual(len(self.describer.calls), 4)
        self.assertEqual(len(self.store.entries), 4)

    def test_other_options_make_a_new_entry_but_secrets_do_not(self) -> None:
        self.describe(self.cached(base_url="http://a"))
        self.describe(self.cached(base_url="http://b"))
        self.describe(self.cached(base_url="http://b", api_key="rotated"))
        self.assertEqual(len(self.describer.calls), 2)

    def test_an_unreadable_entry_is_described_again(self) -> None:
        self.describe(self.cached())
        (key,) = self.store.entries
        self.store.entries[key] = b"\xff"
        with self.assertLogs("oddjob.lib.describe", "WARNING"):
            self.assertEqual(self.describe(self.cached()), "a cat")
        self.assertEqual(len(self.describer.calls), 2)


class DescribeStepTests(unittest.TestCase):
    def test_writes_the_description_next_to_the_image(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        image = tmp / "cat.jpg"
        image.write_bytes(b"jpeg")
        describer = FakeDescriber()
        job = Job(
            steps=[(DescribeStep(describer, "the prompt"), "Describing")],
            dest_fn=suffix_destination(DESCRIPTION_EXTENSION),
        )
        dest = job.run(image, NullReporter())
        self.assertEqual(dest, tmp / "cat.description.txt")
        self.assertEqual(dest.read_text(encoding="utf-8"), "a cat")
        self.assertEqual(describer.calls, [(image, "the prompt")])

    def test_describe_image_returns_the_stripped_text(self) -> None:
        describer = FakeDescriber()
        text = describe_image(describer, "p", Path("cat.jpg"), NullReporter())
        self.assertEqual(text, "a cat")
        self.assertEqual(describer.calls, [(Path("cat.jpg"), "p")])

    def test_prompt_takes_optional_instructions(self) -> None:
        self.assertIn("in Spanish", Prompts().render_describe("in Spanish", None))
        self.assertNotIn("{", Prompts().render_describe(None, None))

    def test_prompt_appends_the_reply_language_only_when_given(self) -> None:
        self.assertTrue(
            Prompts().render_describe(None, "Spanish").endswith(" Reply in Spanish.")
        )
        self.assertNotIn("Reply in", Prompts().render_describe(None, None))


class LanguageTests(unittest.TestCase):
    def test_language_codes_become_names(self) -> None:
        self.assertEqual(language_name("es"), "Spanish")
        self.assertEqual(language_name("pt_BR"), "Portuguese (Brazil)")

    def test_other_text_is_kept(self) -> None:
        self.assertEqual(
            language_name(" Brazilian Portuguese "), "Brazilian Portuguese"
        )

    def test_locale_names_a_language(self) -> None:
        self.assertEqual(locale_language("es_ES.UTF-8"), "Spanish (Spain)")
        self.assertEqual(locale_language("ca_ES@valencia"), "Catalan (Spain)")

    def test_locales_without_a_language_give_none(self) -> None:
        for locale_name in (None, "", "C", "POSIX", "C.UTF-8"):
            with self.subTest(locale_name=locale_name):
                self.assertIsNone(locale_language(locale_name))


class DescribeCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.tmp / "cat.jpg").write_bytes(b"jpeg")
        (self.tmp / "notes.txt").write_text("not an image", encoding="utf-8")
        self.runner = CliRunner()
        for name in ("filejobs", "oddjob"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def test_dry_run_needs_no_backend_and_takes_only_images(self) -> None:
        no_backend = {
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
            "ODDJOB_DESCRIBE_BACKEND": None,
        }
        result = self.runner.invoke(
            describe.describe_cmd, ["-n", "-w", str(self.tmp)], env=no_backend
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"{self.tmp / 'cat.jpg'} -> {self.tmp / 'cat.description.txt'}\n",
        )

    def with_fake_llm(self) -> tuple[Path, dict[str, str | None]]:
        """A fake llm CLI and the environment whose config selects it."""
        llm = write_executable(self.tmp, "llm", ECHO_LLM)
        config = self.tmp / "config" / "oddjob"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(
            f'[tasks]\ndescribe = "llm"\n\n[backends.llm]\nbinary = "{llm}"\n',
            encoding="utf-8",
        )
        return llm, {
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
            "LC_ALL": "C",
        }

    def test_overwrite_and_dry_run_need_write(self) -> None:
        for flag in ("-y", "-n"):
            with self.subTest(flag=flag):
                result = self.runner.invoke(
                    describe.describe_cmd, [flag, str(self.tmp)]
                )
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn("need -w or -o", result.output)

    def test_prints_descriptions_and_writes_nothing_by_default(self) -> None:
        llm, env = self.with_fake_llm()
        image = self.tmp / "cat.jpg"
        result = self.runner.invoke(describe.describe_cmd, [str(image)], env=env)
        self.assertEqual(result.exit_code, 0, result.output)
        # The fake echoes "<system prompt>|<user text>"; describe sends no text.
        self.assertRegex(result.stdout, rf"^{image}: Describe the image .*\|\n$")
        self.assertFalse((self.tmp / "cat.description.txt").exists())
        self.assertEqual(recorded_argv(llm)[-2:], ["-a", str(image)])

    def test_output_implies_write(self) -> None:
        _, env = self.with_fake_llm()
        output = self.tmp / "out.txt"
        image = str(self.tmp / "cat.jpg")
        result = self.runner.invoke(
            describe.describe_cmd, ["-o", str(output), image], env=env
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        self.assertTrue(output.read_text(encoding="utf-8").startswith("Describe"))

    def test_write_lands_the_sidecar_silently(self) -> None:
        llm, env = self.with_fake_llm()
        image = self.tmp / "cat.jpg"
        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(
                describe.describe_cmd,
                ["-v", "-w", "-i", "in Spanish", str(image)],
                env=env,
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        destination = self.tmp / "cat.description.txt"
        self.assertIn(f"wrote {destination}", [r.getMessage() for r in logs.records])
        argv = recorded_argv(llm)
        self.assertEqual(argv[-2:], ["-a", str(image)])
        self.assertIn("in Spanish", argv[argv.index("-s") + 1])

    def test_language_option_is_added_to_the_prompt(self) -> None:
        llm, env = self.with_fake_llm()
        result = self.runner.invoke(
            describe.describe_cmd, ["-l", "fr", str(self.tmp / "cat.jpg")], env=env
        )
        self.assertEqual(result.exit_code, 0, result.output)
        argv = recorded_argv(llm)
        self.assertTrue(argv[argv.index("-s") + 1].endswith(" Reply in French."))

    def test_without_option_or_locale_the_prompt_names_no_language(self) -> None:
        llm, env = self.with_fake_llm()
        self.runner.invoke(describe.describe_cmd, [str(self.tmp / "cat.jpg")], env=env)
        argv = recorded_argv(llm)
        self.assertNotIn("Reply in", argv[argv.index("-s") + 1])

    def test_locale_is_the_default_language(self) -> None:
        llm, env = self.with_fake_llm()
        for name in ("es_ES.UTF-8", "C.UTF-8"):
            with self.subTest(locale=name):
                if name != "C.UTF-8":
                    probe = locale.setlocale(locale.LC_MESSAGES)
                    self.addCleanup(locale.setlocale, locale.LC_MESSAGES, probe)
                    try:
                        locale.setlocale(locale.LC_MESSAGES, name)
                    except locale.Error:
                        self.skipTest(f"locale {name} not installed")
                self.runner.invoke(
                    describe.describe_cmd,
                    [str(self.tmp / "cat.jpg")],
                    env={**env, "LC_ALL": name},
                )
                argv = recorded_argv(llm)
                prompt = argv[argv.index("-s") + 1]
                self.assertEqual("Reply in" in prompt, name == "es_ES.UTF-8")

    def test_second_run_is_served_from_the_cache(self) -> None:
        llm, env = self.with_fake_llm()
        image = str(self.tmp / "cat.jpg")
        first = self.runner.invoke(describe.describe_cmd, [image], env=env)
        self.assertEqual(first.exit_code, 0, first.output)
        llm.unlink()
        second = self.runner.invoke(describe.describe_cmd, [image], env=env)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertEqual(second.stdout, first.stdout)

    def test_a_configured_model_change_misses_the_cache(self) -> None:
        llm, env = self.with_fake_llm()
        config = self.tmp / "config" / "oddjob" / "config.toml"
        image = str(self.tmp / "cat.jpg")
        self.runner.invoke(describe.describe_cmd, [image], env=env)
        config.write_text(
            config.read_text(encoding="utf-8") + 'model = "other"\n', encoding="utf-8"
        )
        llm.write_text(llm.read_text(encoding="utf-8") + "\n# changed\n")
        result = self.runner.invoke(describe.describe_cmd, [image], env=env)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("other", recorded_argv(llm))

    def test_no_cache_describes_every_time(self) -> None:
        llm, env = self.with_fake_llm()
        image = str(self.tmp / "cat.jpg")
        for _ in range(2):
            result = self.runner.invoke(
                describe.describe_cmd, ["--no-cache", image], env=env
            )
            self.assertEqual(result.exit_code, 0, result.output)
        llm.unlink()
        failed = self.runner.invoke(
            describe.describe_cmd, ["--no-cache", image], env=env
        )
        self.assertNotEqual(failed.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
