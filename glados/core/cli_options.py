"""Click options and argument helpers with no backend knowledge.

Shared by glados' task commands and by multitool; nothing here imports the
backend registry or the glados config (those live in core/cli_common.py).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path

import rich_click as click
from foundation.clilib import click_logging_options
from foundation.loglib import setup_logger_from_click

from glados.core.batch import BatchReport

type Decorator[F] = Callable[[F], F]


def output_option[F: Callable[..., object]](func: F) -> F:
    """-o/--output: one explicit destination path."""
    return click.option(
        "-o",
        "--output",
        type=click.Path(path_type=Path, dir_okay=False),
        default=None,
        help="explicit destination path (default: task-specific naming — see this command's --help)",
    )(func)


def overwrite_option[F: Callable[..., object]](func: F) -> F:
    """-y/--overwrite: replace a destination that already exists."""
    return click.option(
        "-y",
        "--overwrite",
        is_flag=True,
        default=False,
        help="overwrite the destination if it already exists",
    )(func)


def common_file_options[F: Callable[..., object]](func: F) -> F:
    """-o/--output and -y/--overwrite, identical across every task."""
    return output_option(overwrite_option(func))


def dry_run_option[F: Callable[..., object]](func: F) -> F:
    """-n/--dry-run: print the planned operations and change nothing."""
    return click.option(
        "-n",
        "--dry-run",
        is_flag=True,
        default=False,
        help="print what would be done, change nothing",
    )(func)


def paths_argument[F: Callable[..., object]](func: F) -> F:
    """PATH...: one or more existing files or directories (see core/inputs.py)."""
    return click.argument(
        "paths",
        nargs=-1,
        required=True,
        type=click.Path(exists=True, path_type=Path),
    )(func)


def logging_options_for[F: Callable[..., object]](app_logger: str) -> Decorator[F]:
    """--log-level, -v/--verbose and -q/--quiet from foundation.clilib, set up
    through foundation.loglib for the `app_logger` logger before the command
    runs. Without them the level comes from <APP_LOGGER>_LOG_LEVEL, else
    warning."""

    def decorator(func: F) -> F:
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
                app_logger, log_level=log_level, verbose=verbose, quiet=quiet
            )
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def finish_batch(report: BatchReport) -> None:
    """Print the summary of a batch run; exit 1 if any input failed. Each
    failure was already logged when it happened (core/batch.py)."""
    if report.failures:
        click.echo(f"{report.succeeded} done, {len(report.failures)} failed", err=True)
        raise click.exceptions.Exit(1)
