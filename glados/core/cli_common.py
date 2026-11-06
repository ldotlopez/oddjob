"""Shared Click plumbing: common options and the per-invocation context
object every task command reads from.

GladosContext is the same object whether a command runs under the
`glados` group (`glados transcribe ...`) or as its own standalone tool
(`transcribe ...`, no group at all) — click.make_pass_decorator's
ensure=True calls ctx.ensure_object() for us, which creates a default
instance when no parent group already put one on the context, so leaf
commands never have to special-case which way they were invoked.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import rich_click as click
from dotenv import load_dotenv
from foundation.clilib import click_logging_options
from foundation.loglib import setup_logger_from_click

from glados.core.backends import BackendError, check_config, resolve
from glados.core.config import Config, ConfigError, config_path, load_config
from glados.core.pipeline import Job
from glados.core.progress import create_reporter

APP_LOGGER = "glados"

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class GladosContext:
    """What every task command needs: the configuration (loaded once, on
    first use, never at import), the backend for its task, and running its
    Job with progress reporting. Errors become a clean message + exit
    code instead of every task repeating the same try/except block."""

    _config: Config | None = None

    def config(self) -> Config:
        if self._config is None:
            load_dotenv()
            path = config_path()
            LOGGER.debug(
                "config: %s (%s)", path, "found" if path.is_file() else "not found"
            )
            try:
                cfg = load_config(path)
                check_config(cfg)
            except (ConfigError, BackendError) as exc:
                raise click.ClickException(str(exc)) from exc
            self._config = cfg
        return self._config

    def backend[T](
        self,
        task: str,
        protocol: type[T],
        choice: str | None,
        overrides: Mapping[str, object],
    ) -> T:
        """The backend object for `task`: see core.backends.resolve."""
        try:
            return resolve(task, protocol, choice, self.config(), overrides)
        except BackendError as exc:
            raise click.ClickException(str(exc)) from exc

    def run_job(self, job: Job, input_path: Path, overwrite: bool) -> None:
        try:
            with create_reporter() as reporter:
                dest = job.run(input_path, reporter, overwrite=overwrite)
        except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Wrote {dest}")


pass_glados_context = click.make_pass_decorator(GladosContext, ensure=True)


def common_file_options[F: Callable[..., object]](func: F) -> F:
    """-o/--output and -y/--overwrite are identical across every task
    (transcribe, rewrite, summarize, expand, ...future ones) — defined
    once here instead of repeated per command."""

    @click.option(
        "-o",
        "--output",
        type=click.Path(path_type=Path, dir_okay=False),
        default=None,
        help="explicit destination path (default: task-specific naming — see this command's --help)",
    )
    @click.option(
        "-y",
        "--overwrite",
        is_flag=True,
        default=False,
        help="overwrite the destination if it already exists",
    )
    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> object:
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def logging_options[F: Callable[..., object]](func: F) -> F:
    """--log-level, -v/--verbose and -q/--quiet from foundation.clilib, set
    up through foundation.loglib before the command runs. Without them the
    level comes from GLADOS_LOG_LEVEL, else warning. Applied per task
    command so it works the same under `glados` and standalone."""

    @click_logging_options
    @functools.wraps(func)
    def wrapper(
        *args: object,
        log_level: str | None,
        verbose: int,
        quiet: int,
        **kwargs: object,
    ) -> object:
        setup_logger_from_click(
            APP_LOGGER, log_level=log_level, verbose=verbose, quiet=quiet
        )
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def backend_option[F: Callable[..., object]](task: str) -> Callable[[F], F]:
    """-b/--backend, also read from GLADOS_<TASK>_BACKEND. Validated when
    the command runs, against the backends installed for `task`."""
    envvar = f"GLADOS_{task.upper()}_BACKEND"

    def decorator(func: F) -> F:
        option = click.option(
            "-b",
            "--backend",
            default=None,
            envvar=envvar,
            show_envvar=True,
            help=f"backend to use (default: [tasks] {task} in the config,"
            " or the only one installed)",
        )
        return option(func)  # type: ignore[return-value]

    return decorator


def model_option[F: Callable[..., object]](func: F) -> F:
    """-m/--model: overrides the backend's global `model` option. A
    backend without one rejects it when it loads."""
    return click.option(
        "-m",
        "--model",
        default=None,
        help="model file/name, overriding [backends.<name>] model",
    )(func)
