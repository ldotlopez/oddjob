"""Shared Click plumbing: common options, and pass_session, which hands
every task command the run's Session (core/session.py).

The Session lives on click's context object (ctx.obj), so it is the same
one whether a command runs under the `oddjob` group (`oddjob transcribe
...`) or as its own standalone tool (`transcribe ...`, no group at all):
ensure_object() creates it when no parent group already did, and leaf
commands never have to special-case which way they were invoked.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Concatenate

import rich_click as click

from filejobs.cli_options import logging_options_for
from oddjob.core.backends import BackendError
from oddjob.core.config import ConfigError
from oddjob.core.session import Session

APP_LOGGER = "oddjob"

LOGGER = logging.getLogger(__name__)


def pass_session[**P, R](func: Callable[Concatenate[Session, P], R]) -> Callable[P, R]:
    """Passes the run's Session as the first argument and turns its config
    and backend errors into a clean message and exit code. Put it nearest
    the function, below every click option."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        session = click.get_current_context().ensure_object(Session)
        try:
            return func(session, *args, **kwargs)
        except (ConfigError, BackendError) as exc:
            raise click.ClickException(str(exc)) from exc

    return wrapper


# --log-level/-v/-q for every oddjob task command, on the `oddjob` logger
# (ODDJOB_LOG_LEVEL when no flag is given).
logging_options = logging_options_for(APP_LOGGER)


def backend_option[F: Callable[..., object]](task: str) -> Callable[[F], F]:
    """-b/--backend, also read from ODDJOB_<TASK>_BACKEND. Validated when
    the command runs, against the backends installed for `task`."""
    envvar = f"ODDJOB_{task.upper()}_BACKEND"

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
