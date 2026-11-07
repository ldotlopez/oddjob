"""glados' config and backends for one run, without click.

`Glados` is what Python code (a command, a composed tool, a test) asks for
a backend: the config is loaded on first use and cached, and backends come
back typed and checked against their task Protocol. Errors are the specific
ConfigError and BackendError; turning them into exit codes is the CLI's job
(core/cli_common.pass_glados).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from dotenv import load_dotenv

from glados.core.backends import check_config, resolve
from glados.core.config import Config, config_path, load_config

LOGGER = logging.getLogger(__name__)

type ConfigLoader = Callable[[], Config]


def load_default_config() -> Config:
    """`.env`, then config_path(), loaded and checked against the installed
    backends. Raises ConfigError or BackendError."""
    load_dotenv()
    path = config_path()
    LOGGER.debug("config: %s (%s)", path, "found" if path.is_file() else "not found")
    cfg = load_config(path)
    check_config(cfg)
    return cfg


class Glados:
    """glados' config and backends for one run. The config is loaded on
    first use and cached; nothing happens at construction. A failed load is
    not cached, so the next call retries."""

    def __init__(self, load: ConfigLoader = load_default_config) -> None:
        self._load = load
        self._config: Config | None = None

    def config(self) -> Config:
        if self._config is None:
            self._config = self._load()
        return self._config

    def backend[T](
        self,
        task: str,
        protocol: type[T],
        choice: str | None = None,
        overrides: Mapping[str, object] | None = None,
    ) -> T:
        """The backend object for `task`, checked against `protocol`: see
        core.backends.resolve. Raises BackendError (or ConfigError on the
        first call, from loading the config)."""
        return resolve(task, protocol, choice, self.config(), overrides or {})
