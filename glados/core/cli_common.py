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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import rich_click as click

from glados.core.pipeline import Job
from glados.core.progress import create_reporter


@dataclass(slots=True)
class GladosContext:
    """Holds the one piece of behavior every task command needs once its
    Job is built: run it, report progress, and turn the pipeline's
    exceptions into a clean error message + exit code — instead of every
    task module repeating the same try/except/print block."""

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


def backend_option[F: Callable[..., object]](
    backends: dict[str, object], default: str | None
) -> Callable[[F], F]:
    """-b/--backend, with choices/default sourced from the calling task's
    own BACKENDS registry — the option's shape is shared even though its
    registry contents (and whether it's non-empty yet) aren't."""

    def decorator(func: F) -> F:
        option = click.option(
            "-b",
            "--backend",
            type=click.Choice(sorted(backends)) if backends else str,
            default=default,
            help=f"backend to use (default: {default})"
            if default
            else "backend to use (none implemented yet)",
        )
        return option(func)  # type: ignore[return-value]

    return decorator


def model_option[F: Callable[..., object]](func: F) -> F:
    """-m/--model — shape (an optional model file/name) is shared even
    though what it means varies per backend."""
    return click.option(
        "-m",
        "--model",
        type=click.Path(path_type=Path),
        default=None,
        help="model file/name for backends that use one",
    )(func)
