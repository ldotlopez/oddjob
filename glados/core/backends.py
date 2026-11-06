"""Backend selection and loading.

Which backend implements which task is read from the package's entry-point
metadata (one group per task, see pyproject.toml), so nothing is imported to
know it. Several backends may live in one module: each entry point's value
names the module (`glados.plugins.<module>:__glados_plugin__`). Only the
selected backend's module is imported, through foundation.plugin.Register:
its entry point receives the backend name and its global options and returns
`(task name, task Protocol, object)` triples. See docs/decisions/0002 for
why, and how to change it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import Any

import pydantic
from foundation.plugin import PluginError, Register

from glados.core.config import Config, ConfigError, validation_message

TASKS = ("transcribe", "rewrite", "summarize", "expand", "translate", "describe")

PLUGINS_NAMESPACE = "glados.plugins"
PLUGIN_ENTRY_POINT = "__glados_plugin__"
_GROUP_PREFIX = "glados.backends."
_ENTRY_RE = re.compile(
    rf"^{re.escape(PLUGINS_NAMESPACE)}\.(\w+):{re.escape(PLUGIN_ENTRY_POINT)}$"
)

LOGGER = logging.getLogger(__name__)


class BackendError(Exception):
    """No usable backend for a task, or the selected one failed to load."""


def _modules(task: str) -> dict[str, str]:
    """The backends that implement `task`, mapped to the plugin module that
    provides each, from installed metadata. Imports nothing."""
    modules: dict[str, str] = {}
    for entry in entry_points(group=f"{_GROUP_PREFIX}{task}"):
        match = _ENTRY_RE.match(entry.value)
        if match is None:
            raise BackendError(
                f"entry point {entry.group}:{entry.name} must be"
                f" '{PLUGINS_NAMESPACE}.<module>:{PLUGIN_ENTRY_POINT}',"
                f" not {entry.value!r}"
            )
        modules[entry.name] = match.group(1)
    return modules


def implementors(task: str) -> list[str]:
    """The sorted names of the backends that implement `task`, from
    installed metadata. Imports nothing."""
    return sorted(_modules(task))


def check_config(cfg: Config) -> None:
    """Check every task and backend name in `cfg` against the metadata, and
    that each backend comes from the same module for every task it
    implements. Backend options are not checked here: that needs loading
    the backend."""
    _check_one_module_per_backend()
    available = {task: implementors(task) for task in TASKS}
    for task, name in cfg.tasks.items():
        if task not in available:
            raise ConfigError(f"tasks.{task}: unknown task (known: {', '.join(TASKS)})")
        if name not in available[task]:
            raise ConfigError(
                f"tasks.{task}: {_not_implemented(name, task, available[task])}"
            )
    known = {name for names in available.values() for name in names}
    for name in cfg.backends:
        if name not in known:
            raise ConfigError(
                f"backends.{name}: unknown backend"
                f" (known: {', '.join(sorted(known)) or 'none'})"
            )


def select(task: str, choice: str | None, cfg: Config) -> str:
    """The backend for `task`: `choice` (CLI switch or env var), else
    `[tasks]` in the config, else the only implementor."""
    candidates = implementors(task)
    name = choice or cfg.tasks.get(task)
    if name is not None:
        if name not in candidates:
            raise BackendError(_not_implemented(name, task, candidates))
        source = "-b/environment" if choice else "config [tasks]"
        LOGGER.debug("%s: backend %s (from %s)", task, name, source)
        return name
    if len(candidates) == 1:
        LOGGER.debug("%s: backend %s (only implementor)", task, candidates[0])
        return candidates[0]
    if not candidates:
        raise BackendError(f"no backend implements {task}")
    raise BackendError(
        f"several backends implement {task} ({', '.join(candidates)}): pass"
        f" -b, set GLADOS_{task.upper()}_BACKEND or [tasks] {task} in the config"
    )


def load[T](name: str, task: str, protocol: type[T], options: Mapping[str, Any]) -> T:
    """Import the module providing backend `name`, build the backend with
    `options` and return its object for `task`, checked against `protocol`."""
    modules = _modules(task)
    if name not in modules:
        raise BackendError(_not_implemented(name, task, sorted(modules)))
    module = modules[name]
    LOGGER.debug(
        "loading backend %s from %s.%s with options %s",
        name,
        PLUGINS_NAMESPACE,
        module,
        sorted(options),
    )
    register = Register(ns=PLUGINS_NAMESPACE, entry_point=PLUGIN_ENTRY_POINT)
    try:
        register.register(module, name, options)
        return register.get_object(module, task, protocol)
    except PluginError as exc:
        cause = exc.__cause__
        if isinstance(cause, pydantic.ValidationError):
            raise BackendError(
                f"invalid options for backend {name}:\n"
                + validation_message(f"backends.{name}", cause)
            ) from exc
        raise BackendError(f"backend {name}: {exc}") from exc


def resolve[T](
    task: str,
    protocol: type[T],
    choice: str | None,
    cfg: Config,
    overrides: Mapping[str, Any],
) -> T:
    """Select the backend for `task` and load it with its global options:
    the backend's defaults, then `[backends.<name>]`, then `overrides`
    (CLI flags; None means not given)."""
    name = select(task, choice, cfg)
    options = {
        **cfg.backends.get(name, {}),
        **{key: value for key, value in overrides.items() if value is not None},
    }
    return load(name, task, protocol, options)


def _check_one_module_per_backend() -> None:
    seen: dict[str, tuple[str, str]] = {}
    for task in TASKS:
        for name, module in _modules(task).items():
            first_task, first_module = seen.setdefault(name, (task, module))
            if module != first_module:
                raise BackendError(
                    f"backend {name!r} comes from module {first_module!r} for"
                    f" {first_task} but from {module!r} for {task}"
                )


def _not_implemented(name: str, task: str, candidates: list[str]) -> str:
    return (
        f"backend {name!r} does not implement {task}"
        f" (available: {', '.join(candidates) or 'none'})"
    )
