"""translate: the language infix, its prompt, and the command end to end
through the llm backend's fake executable."""

import logging
import tempfile
import unittest
from pathlib import Path

import pydantic
from click.testing import CliRunner
from support import write_executable
from test_llm import ECHO_LLM

from glados.commands import translate
from glados.core.config import Prompts
from glados.lib.translate import language_infix


class LanguageInfixTests(unittest.TestCase):
    def test_infixes(self) -> None:
        cases = {
            "es": "es",
            "Brazilian Portuguese": "brazilian-portuguese",
            " pt-BR ": "pt-br",
            "Français": "français",
            "zh (simplified)": "zh-simplified",
        }
        for language, expected in cases.items():
            with self.subTest(language=language):
                self.assertEqual(language_infix(language), expected)

    def test_a_language_with_no_word_characters_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            language_infix(" ./ ")


class TranslatePromptTests(unittest.TestCase):
    def test_render_fills_the_language(self) -> None:
        self.assertIn("into Spanish,", Prompts().render_translate("Spanish"))

    def test_only_the_language_placeholder_is_allowed(self) -> None:
        Prompts(translate="Into {language}.")
        with self.assertRaisesRegex(pydantic.ValidationError, "length"):
            Prompts(translate="Into {language}. {length}")


class TranslateCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.tmp / "notes.txt").write_text("hola", encoding="utf-8")
        (self.tmp / "notes.es.txt").write_text("earlier output", encoding="utf-8")
        self.runner = CliRunner()
        self.no_backend = {
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "GLADOS_TRANSLATE_BACKEND": None,
        }
        for name in ("filejobs", "glados"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def test_dry_run_needs_no_backend_and_skips_earlier_outputs(self) -> None:
        result = self.runner.invoke(
            translate.cli, ["-n", "-l", "ES", str(self.tmp)], env=self.no_backend
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"{self.tmp / 'notes.txt'} -> {self.tmp / 'notes.es.txt'}\n",
        )

    def test_language_is_required_and_must_name_a_file(self) -> None:
        missing = self.runner.invoke(translate.cli, [str(self.tmp)])
        unusable = self.runner.invoke(translate.cli, ["-l", "//", str(self.tmp)])
        self.assertEqual((missing.exit_code, unusable.exit_code), (2, 2))

    def with_fake_llm(self) -> dict[str, str | None]:
        """The environment of a run whose config selects a fake llm CLI."""
        llm = write_executable(self.tmp, "llm", ECHO_LLM)
        config = self.tmp / "config" / "glados"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(
            f'[tasks]\ntranslate = "llm"\n\n[backends.llm]\nbinary = "{llm}"\n',
            encoding="utf-8",
        )
        return {"XDG_CONFIG_HOME": str(self.tmp / "config")}

    def test_an_existing_destination_fails_and_the_rest_runs(self) -> None:
        (self.tmp / "other.txt").write_text("adiós", encoding="utf-8")
        result = self.runner.invoke(
            translate.cli, ["-l", "es", str(self.tmp)], env=self.with_fake_llm()
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("1 done, 1 failed", result.stderr)
        self.assertEqual(
            (self.tmp / "notes.es.txt").read_text(encoding="utf-8"), "earlier output"
        )
        self.assertTrue((self.tmp / "other.es.txt").exists())

    def test_translates_through_the_selected_backend_silently(self) -> None:
        env = self.with_fake_llm()
        args = ["-v", "-l", "Brazilian Portuguese", str(self.tmp / "notes.txt")]
        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(translate.cli, args, env=env)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        destination = self.tmp / "notes.brazilian-portuguese.txt"
        self.assertIn(f"wrote {destination}", [r.getMessage() for r in logs.records])
        system, user = destination.read_text(encoding="utf-8").split("|")
        self.assertIn("into Brazilian Portuguese,", system)
        self.assertEqual(user, "hola")


if __name__ == "__main__":
    unittest.main()
