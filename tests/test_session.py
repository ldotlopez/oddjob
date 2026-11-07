"""Glados (core/session.py) and pass_glados (core/cli_common.py): the
config loaded once on first use, typed backends, and the click glue that
turns their errors into a clean exit."""

import tempfile
import unittest
from pathlib import Path

import rich_click as click
from click.testing import CliRunner

from glados.cli import cli
from glados.core.backends import BackendError
from glados.core.cli_common import pass_glados
from glados.core.config import Config, ConfigError
from glados.core.session import Glados
from glados.lib.protocols import Summarizer


class CountingLoader:
    """Returns `cfg`, or raises `error` while `failures` is above zero,
    counting the calls."""

    def __init__(
        self, cfg: Config, error: Exception | None = None, failures: int = 0
    ) -> None:
        self.cfg = cfg
        self.error = error
        self.failures = failures
        self.calls = 0

    def __call__(self) -> Config:
        self.calls += 1
        if self.error is not None and self.failures > 0:
            self.failures -= 1
            raise self.error
        return self.cfg


class GladosTests(unittest.TestCase):
    def test_config_is_loaded_on_first_use_and_cached(self) -> None:
        loader = CountingLoader(Config())
        glados = Glados(loader)
        self.assertEqual(loader.calls, 0)
        first = glados.config()
        self.assertIs(glados.config(), first)
        self.assertEqual(loader.calls, 1)

    def test_failed_load_propagates_and_is_retried(self) -> None:
        loader = CountingLoader(Config(), ConfigError("bad config"), failures=1)
        glados = Glados(loader)
        with self.assertRaisesRegex(ConfigError, "bad config"):
            glados.config()
        self.assertEqual(glados.config(), Config())
        self.assertEqual(loader.calls, 2)

    def test_unknown_backend_raises_backend_error(self) -> None:
        glados = Glados(lambda: Config())
        with self.assertRaisesRegex(BackendError, "available: .*openai"):
            glados.backend("summarize", Summarizer, choice="nope")

    def test_backend_from_config_is_typed(self) -> None:
        cfg = Config(
            tasks={"summarize": "openai"},
            backends={"openai": {"model": "test-model"}},
        )
        summarizer = Glados(lambda: cfg).backend("summarize", Summarizer)
        self.assertIsInstance(summarizer, Summarizer)

    def test_cli_override_reaches_backend_options(self) -> None:
        glados = Glados(lambda: Config(tasks={"summarize": "openai"}))
        with self.assertRaisesRegex(BackendError, "invalid options.*openai"):
            glados.backend("summarize", Summarizer, overrides={"timeout": "soon"})


class PassGladosTests(unittest.TestCase):
    def command(self, seen: list[Glados]) -> click.Command:
        @click.command()
        @click.option("--name", default="x")
        @pass_glados
        def command(glados: Glados, name: str) -> None:
            seen.append(glados)
            glados.config()
            click.echo(name)

        return command

    def test_errors_become_a_clean_exit(self) -> None:
        glados = Glados(CountingLoader(Config(), ConfigError("bad config"), 1))
        result = CliRunner().invoke(self.command([]), [], obj=glados)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("bad config", result.output)
        self.assertNotIsInstance(result.exception, ConfigError)

    def test_uses_the_group_glados_and_passes_options(self) -> None:
        seen: list[Glados] = []
        glados = Glados(lambda: Config())
        result = CliRunner().invoke(self.command(seen), ["--name", "y"], obj=glados)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output, "y\n")
        self.assertEqual(seen, [glados])

    def test_standalone_creates_a_glados(self) -> None:
        seen: list[Glados] = []

        @click.command()
        @pass_glados
        def command(glados: Glados) -> None:
            seen.append(glados)

        result = CliRunner().invoke(command, [])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsInstance(seen[0], Glados)


class FileCommandsIgnoreConfigTests(unittest.TestCase):
    """A command without pass_glados never loads config, so a broken one
    cannot break it; a task command on the same Glados reports the error."""

    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.tmp / "note.txt").write_text("hello", encoding="utf-8")
        self.loader = CountingLoader(Config(), ConfigError("bad config"), 99)

    def test_file_command_runs_without_loading_config(self) -> None:
        result = CliRunner().invoke(
            cli, ["sidecars", "scan", str(self.tmp)], obj=Glados(self.loader)
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.loader.calls, 0)

    def test_task_command_reports_the_broken_config(self) -> None:
        result = CliRunner().invoke(
            cli, ["summarize", str(self.tmp / "note.txt")], obj=Glados(self.loader)
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("bad config", result.output)
        self.assertEqual(self.loader.calls, 1)


if __name__ == "__main__":
    unittest.main()
