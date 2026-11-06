"""Click options and job runners with no backend knowledge.

Shared by glados' task commands and by multitool; nothing here imports the
backend registry or the glados config (those live in core/cli_common.py).
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Sequence
from pathlib import Path

import rich_click as click
from foundation.clilib import click_logging_options
from foundation.loglib import setup_logger_from_click

from glados.core.batch import BatchReport, run_batch
from glados.core.pipeline import JOB_ERRORS, Job
from glados.core.progress import BaseProgressReporter, create_reporter

type Decorator[F] = Callable[[F], F]


def output_option[F: Callable[..., object]](func: F) -> F:
    """-o/--output: one explicit destination path."""
    return click.option(
        "-o",
        "--output",
        type=click.Path(path_type=Path, dir_okay=False),
        default=None,
        help="explicit destination path, only with a single input file"
        " (default: task-specific naming — see this command's --help)",
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


def check_single_output(output: Path | None, inputs: Sequence[Path]) -> None:
    """-o names one destination, so it needs exactly one input file."""
    if output is not None and len(inputs) != 1:
        raise click.UsageError(
            f"-o/--output needs exactly one input file, got {len(inputs)}"
        )


def finish_batch(*reports: BatchReport) -> None:
    """Print the summary of batch runs; exit 1 if any input failed. Each
    failure was already logged when it happened (core/batch.py)."""
    succeeded = sum(report.succeeded for report in reports)
    failed = sum(len(report.failures) for report in reports)
    if failed:
        click.echo(f"{succeeded} done, {failed} failed", err=True)
        raise click.exceptions.Exit(1)


def run_jobs(
    job: Job, inputs: Sequence[Path], overwrite: bool, description: str
) -> None:
    """Run `job` on every input file, print where each result landed, then
    the batch summary."""
    written: list[Path] = []

    def run(input_path: Path, reporter: BaseProgressReporter) -> None:
        written.append(job.run(input_path, reporter, overwrite=overwrite))

    report = run_batch(inputs, run, description=description)
    for dest in written:
        click.echo(f"Wrote {dest}")
    finish_batch(report)


def run_single_job(job: Job, input_path: Path, overwrite: bool) -> Path:
    """Run `job` on one input; a failure becomes a clean error message."""
    try:
        with create_reporter() as reporter:
            return job.run(input_path, reporter, overwrite=overwrite)
    except JOB_ERRORS as exc:
        raise click.ClickException(str(exc)) from exc
