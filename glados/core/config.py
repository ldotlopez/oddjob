"""User configuration: an optional TOML file in the user config directory.

glados runs without it; every backend option has a default. The file can
select a backend per task (`[tasks]`) and give a backend's global options
(`[backends.<name>]`). `${VAR}` placeholders are expanded from the
environment before parsing; write a literal `$` as `$$`.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from string import Template
from typing import Any

import pydantic
from platformdirs import user_config_path


class ConfigError(Exception):
    """The configuration file is unreadable or invalid."""


class Config(pydantic.BaseModel):
    """`tasks` maps a task name to the backend that runs it; `backends`
    maps a backend name to its global options, validated by the backend
    itself when it loads."""

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    tasks: dict[str, str] = {}
    backends: dict[str, dict[str, Any]] = {}


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
