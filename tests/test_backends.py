"""core/backends.py and the backend part of core/config.py: the task list
from entry-point metadata, and per-task backend options
(`[backends.<name>.tasks.<task>]`, decision 0010)."""

import re
import unittest

import pydantic

from oddjob.cli import TASK_COMMANDS
from oddjob.core.backends import check_config, resolve, tasks
from oddjob.core.config import Config, ConfigError
from oddjob.lib.protocols import Describer, Translator

BACKEND_ENVVAR = re.compile(r"^ODDJOB_(\w+)_BACKEND$")


class TaskListTests(unittest.TestCase):
    def test_every_command_backend_names_a_known_task(self) -> None:
        known = tasks()
        checked = []
        for command in TASK_COMMANDS:
            for param in command.params:
                if param.name != "backend":
                    continue
                match = BACKEND_ENVVAR.match(str(param.envvar))
                self.assertIsNotNone(match, f"{command.name}: {param.envvar}")
                assert match is not None
                self.assertIn(match.group(1).lower(), known, command.name)
                checked.append(command.name)
        self.assertEqual(len(checked), len(TASK_COMMANDS))

    def test_unknown_task_in_tasks_table_lists_the_known_ones(self) -> None:
        with self.assertRaisesRegex(ConfigError, r"tasks\.nope: unknown task"):
            check_config(Config(tasks={"nope": "openai"}))


class PerTaskOptionsTests(unittest.TestCase):
    cfg = Config(
        backends={
            "openai": {
                "model": "small",
                "timeout": 30,
                "tasks": {"describe": {"model": "vision"}},
            }
        }
    )

    def test_task_table_overrides_the_backend_table_for_that_task_only(self) -> None:
        self.assertEqual(
            self.cfg.backend_options("openai", "describe"),
            {"model": "vision", "timeout": 30},
        )
        self.assertEqual(
            self.cfg.backend_options("openai", "translate"),
            {"model": "small", "timeout": 30},
        )

    def test_unconfigured_backend_has_no_options(self) -> None:
        self.assertEqual(self.cfg.backend_options("ollama", "describe"), {})

    def test_resolve_builds_each_task_with_its_options(self) -> None:
        describer = resolve("describe", Describer, "openai", self.cfg, {})
        translator = resolve("translate", Translator, "openai", self.cfg, {})
        self.assertEqual(describer.transport.options.model, "vision")
        self.assertEqual(translator.transport.options.model, "small")

    def test_cli_override_beats_the_task_table(self) -> None:
        describer = resolve("describe", Describer, "openai", self.cfg, {"model": "cli"})
        self.assertEqual(describer.transport.options.model, "cli")

    def test_valid_task_tables_pass_the_config_check(self) -> None:
        check_config(self.cfg)

    def test_task_table_for_an_unknown_task_is_rejected(self) -> None:
        cfg = Config(backends={"openai": {"tasks": {"nope": {}}}})
        with self.assertRaisesRegex(
            ConfigError, r"backends\.openai\.tasks\.nope: unknown task"
        ):
            check_config(cfg)

    def test_task_table_for_a_task_the_backend_lacks_is_rejected(self) -> None:
        cfg = Config(backends={"openai": {"tasks": {"transcribe": {}}}})
        with self.assertRaisesRegex(
            ConfigError,
            r"backends\.openai\.tasks\.transcribe: backend 'openai' does not"
            r" implement transcribe",
        ):
            check_config(cfg)

    def test_tasks_must_hold_tables(self) -> None:
        with self.assertRaisesRegex(pydantic.ValidationError, r"openai\.tasks must"):
            Config(backends={"openai": {"tasks": {"describe": "vision"}}})


if __name__ == "__main__":
    unittest.main()
