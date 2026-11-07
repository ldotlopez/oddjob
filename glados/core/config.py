"""User configuration: an optional TOML file in the user config directory.

glados runs without it; every backend option has a default. The file can
select a backend per task (`[tasks]`), give a backend's global options
(`[backends.<name>]`) and override the text tasks' prompts (`[prompts]`). `${VAR}` placeholders are expanded from the
environment before parsing; write a literal `$` as `$$`.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from string import Formatter, Template
from typing import Any

import pydantic
from platformdirs import user_config_path


class ConfigError(Exception):
    """The configuration file is unreadable or invalid."""


_PROMPT_PLACEHOLDERS = {
    "rewrite": "instructions",
    "summarize": "length",
    "expand": "length",
    "translate": "language",
    "describe": "instructions",
}


class Prompts(pydantic.BaseModel):
    """System prompt templates for the text tasks, the same for every
    backend. Each may use only its own `str.format` placeholder:
    `{instructions}` in rewrite and describe, `{length}` in summarize and
    expand, `{language}` in translate. Write
    them with plain braces, not `${...}` (that is environment expansion);
    a literal brace is `{{` or `}}`."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    rewrite: str = (
        "Rewrite the text the user sends. {instructions}"
        " Reply with the rewritten text only, in the same language,"
        " with no preamble or commentary."
    )
    summarize: str = (
        "Summarize the text the user sends. {length}"
        " Reply with the summary only, in the same language,"
        " with no preamble or commentary."
    )
    expand: str = (
        "Expand the text the user sends with more detail, explanation and"
        " examples, without changing its meaning. {length}"
        " Reply with the expanded text only, in the same language,"
        " with no preamble or commentary."
    )
    translate: str = (
        "Translate the text the user sends into {language}, keeping its"
        " meaning, tone and formatting. Reply with the translation only,"
        " with no preamble or commentary."
    )
    describe: str = (
        "Describe the image the user sends: its subject, setting and any"
        " visible text. {instructions} Reply with the description only,"
        " with no preamble or commentary."
    )

    @pydantic.field_validator("rewrite", "summarize", "expand", "translate", "describe")
    @classmethod
    def _check_placeholders(cls, value: str, info: pydantic.ValidationInfo) -> str:
        allowed = _PROMPT_PLACEHOLDERS[info.field_name]
        try:
            names = {
                name for _, name, _, _ in Formatter().parse(value) if name is not None
            }
        except ValueError as exc:
            raise ValueError(f"invalid template: {exc}") from exc
        unknown = names - {allowed}
        if unknown:
            raise ValueError(
                f"unknown placeholder(s) {', '.join(sorted(unknown))}"
                f" (allowed: {{{allowed}}})"
            )
        return value

    def render_rewrite(self, instructions: str | None) -> str:
        return self.rewrite.format(instructions=instructions or DEFAULT_INSTRUCTIONS)

    def render_summarize(self, max_words: int | None) -> str:
        return self.summarize.format(length=_length_sentence(max_words))

    def render_expand(self, target_words: int | None) -> str:
        return self.expand.format(length=_length_sentence(target_words))

    def render_translate(self, language: str) -> str:
        return self.translate.format(language=language)

    def render_describe(self, instructions: str | None) -> str:
        return self.describe.format(instructions=instructions or "")


DEFAULT_INSTRUCTIONS = "Improve clarity and correctness without changing the meaning."


def _length_sentence(words: int | None) -> str:
    return f"Keep it to about {words} words." if words else ""


TASK_OPTIONS_KEY = "tasks"


class Config(pydantic.BaseModel):
    """`tasks` maps a task name to the backend that runs it; `backends`
    maps a backend name to its global options, validated by the backend
    itself when it loads, with per-task options in its `tasks` table
    (`[backends.<name>.tasks.<task>]`); `prompts` holds the text tasks'
    prompts."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    tasks: dict[str, str] = {}
    backends: dict[str, dict[str, Any]] = {}
    prompts: Prompts = Prompts()

    @pydantic.field_validator("backends")
    @classmethod
    def _check_task_tables(
        cls, value: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        for name, table in value.items():
            per_task = table.get(TASK_OPTIONS_KEY, {})
            if not isinstance(per_task, dict) or not all(
                isinstance(options, dict) for options in per_task.values()
            ):
                raise ValueError(
                    f"{name}.{TASK_OPTIONS_KEY} must hold one"
                    f" [backends.{name}.{TASK_OPTIONS_KEY}.<task>] table per task"
                )
        return value

    def task_tables(self, backend: str) -> dict[str, dict[str, Any]]:
        """`[backends.<backend>.tasks]`: per-task options, by task."""
        return self.backends.get(backend, {}).get(TASK_OPTIONS_KEY, {})

    def backend_options(self, backend: str, task: str) -> dict[str, Any]:
        """The configured options of `backend` when it runs `task`:
        `[backends.<backend>]`, then `[backends.<backend>.tasks.<task>]` on
        top. The `tasks` table itself is not an option."""
        table = self.backends.get(backend, {})
        shared = {key: value for key, value in table.items() if key != TASK_OPTIONS_KEY}
        return {**shared, **self.task_tables(backend).get(task, {})}


def config_path() -> Path:
    """`$XDG_CONFIG_HOME/glados/config.toml` (or the platform equivalent)."""
    return user_config_path("glados", appauthor=False) / "config.toml"


def validation_message(prefix: str, error: pydantic.ValidationError) -> str:
    """One line per error, each prefixed with `prefix` and the dotted
    location of the offending value."""
    lines: list[str] = []
    for detail in error.errors():
        parts = [prefix] if prefix else []
        location = ".".join([*parts, *(str(part) for part in detail["loc"])])
        lines.append(f"{location}: {detail['msg']}")
    return "\n".join(lines)


def load_config(path: Path) -> Config:
    """Read, expand and validate `path`. A missing file is an empty Config."""
    if not path.is_file():
        return Config()
    try:
        text = Template(path.read_text(encoding="utf-8")).substitute(os.environ)
    except KeyError as exc:
        raise ConfigError(f"{path}: undefined environment variable {exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc} (write a literal '$' as '$$')") from exc
    try:
        return Config.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    except pydantic.ValidationError as exc:
        raise ConfigError(f"{path}:\n{validation_message('', exc)}") from exc
