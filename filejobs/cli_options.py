"""Click options and job runners with no backend knowledge.

Shared by glados' task and file commands; nothing here imports the
backend registry or the glados config (those live in glados/core/cli_common.py).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

import rich_click as click
from foundation.clilib import click_logging_options
from foundation.loglib import setup_logger_from_click

from filejobs.batch import BatchReport, run_batch
from filejobs.pipeline import JOB_ERRORS, DestinationFn, Job
from filejobs.progress import BaseProgressReporter, create_reporter

type Decorator[F] = Callable[[F], F]

LOGGER = logging.getLogger(__name__)
SHARED_LOGGER = "filejobs"


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
    """PATH...: one or more existing files or directories (see filejobs/inputs.py)."""
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
    warning.

    The shared `filejobs` logger follows the app logger's level, so -v also
    shows its progress and `wrote` lines. A bare --log-level level applies
    only to the app logger (foundation.loglib), so the spec is applied again
    after copying the level: an explicit `filejobs:<level>` rule wins."""

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
            setup_logging(app_logger, log_level, verbose, quiet)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def setup_logging(
    app_logger: str, log_level: str | None, verbose: int, quiet: int
) -> None:
    """Set up `app_logger` and give the shared `filejobs` logger its level
    (see logging_options_for). For commands that cannot take -v/-q."""

    def setup() -> logging.Logger:
        return setup_logger_from_click(
            app_logger, log_level=log_level, verbose=verbose, quiet=quiet
        )

    logging.getLogger(SHARED_LOGGER).setLevel(setup().getEffectiveLevel())
    if log_level is not None:
        setup()


def check_single_output(output: Path | None, inputs: Sequence[Path]) -> None:
    """-o names one destination, so it needs exactly one input file."""
    if output is not None and len(inputs) != 1:
        raise click.UsageError(
            f"-o/--output needs exactly one input file, got {len(inputs)}"
        )


def finish_batch(*reports: BatchReport) -> None:
    """Print the summary of batch runs; exit 1 if any input failed. Each
    failure was already logged when it happened (filejobs/batch.py)."""
    succeeded = sum(report.succeeded for report in reports)
    failed = sum(len(report.failures) for report in reports)
    if failed:
        click.echo(f"{succeeded} done, {failed} failed", err=True)
        raise click.exceptions.Exit(1)


def print_plan(inputs: Sequence[Path], dest_fn: DestinationFn) -> None:
    """--dry-run: print where each input would land, change nothing."""
    for input_path in inputs:
        click.echo(f"{input_path} -> {dest_fn(input_path)}")


type JobAction[T] = Callable[[T, BaseProgressReporter], Path | None]


def job_action(job: Job, overwrite: bool) -> JobAction[Path]:
    """Run `job` on one input file, returning where the result landed."""

    def run(input_path: Path, reporter: BaseProgressReporter) -> Path:
        return job.run(input_path, reporter, overwrite=overwrite)

    return run


def run_jobs[T](
    items: Sequence[T],
    action: JobAction[T],
    description: str,
    label: Callable[[T], str] = str,
) -> None:
    """Run `action` on every item, logging each path it wrote at INFO, then
    the batch summary (only on failure, decision 0007). An action returning
    None had nothing to write for that item, which still counts as done."""

    def run(item: T, reporter: BaseProgressReporter) -> None:
        if (written := action(item, reporter)) is not None:
            LOGGER.info("wrote %s", written)

    report = run_batch(items, run, description=description, label=label)
    finish_batch(report)


def run_single_job(job: Job, input_path: Path, overwrite: bool) -> Path:
    """Run `job` on one input; a failure becomes a clean error message."""
    try:
        with create_reporter() as reporter:
            dest = job.run(input_path, reporter, overwrite=overwrite)
    except JOB_ERRORS as exc:
        raise click.ClickException(str(exc)) from exc
    LOGGER.info("wrote %s", dest)
    return dest
