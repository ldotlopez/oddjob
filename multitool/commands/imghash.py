"""`multitool img-hash`, `img-duplicates` and `img-check` (need the
`multitool` extra; multitool.imghash is imported only when one of them
runs)."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import rich_click as click
from foundation.cache import UserCache

from filejobs.batch import run_batch
from filejobs.cli_options import finish_batch, paths_argument
from filejobs.inputs import expand_inputs
from filejobs.pipeline import JOB_ERRORS
from filejobs.progress import BaseProgressReporter
from multitool import media
from multitool.external import run_command_with_paths

CACHE_APP = "multitool"


def load_imghash() -> ModuleType:
    """multitool.imghash, which needs the optional `multitool` extra."""
    try:
        from multitool import imghash
    except ImportError as exc:
        raise click.ClickException(
            f"{exc.name} is missing: install the multitool extra"
            " (uv sync --extra multitool)"
        ) from exc
    return imghash


def hash_options[F: Callable[..., object]](func: F) -> F:
    func = click.option(
        "--no-cache", is_flag=True, help="neither read nor store cached hashes"
    )(func)
    func = click.option(
        "--hash-size",
        type=click.IntRange(min=2),
        default=16,
        show_default=True,
        help="hash side in pixels (bits = size²)",
    )(func)
    return paths_argument(func)


def hash_cache(no_cache: bool, expiration: float) -> UserCache | None:
    """The hash cache, closed when the running command ends."""
    if no_cache:
        return None
    cache = UserCache(app=CACHE_APP, expiration_time=expiration)
    click.get_current_context().call_on_close(cache.close)
    return cache


@click.command("img-hash")
@hash_options
def img_hash_cmd(paths: tuple[Path, ...], hash_size: int, no_cache: bool) -> None:
    """Print the average hash of each image in PATH..."""
    imghash = load_imghash()
    hasher = imghash.ImageHasher(
        hash_size, hash_cache(no_cache, imghash.CACHE_EXPIRATION)
    )
    results: list[tuple[Path, str]] = []

    def collect(path: Path, _reporter: BaseProgressReporter) -> None:
        results.append((path, hasher.hash(path)))

    report = run_batch(
        expand_inputs(paths, media.is_image), collect, description="Hashing"
    )
    for path, image_hash in results:
        click.echo(f"{path}: {image_hash}")
    finish_batch(report)


@click.command("img-check")
@paths_argument
def img_check_cmd(paths: tuple[Path, ...]) -> None:
    """Print each image in PATH... that cannot be fully decoded, with the
    reason; exit 1 if there was any."""
    imghash = load_imghash()
    problems: list[tuple[Path, str]] = []

    def check(path: Path, _reporter: BaseProgressReporter) -> None:
        if (problem := imghash.decode_problem(path)) is not None:
            problems.append((path, problem))

    report = run_batch(
        expand_inputs(paths, media.is_image), check, description="Checking"
    )
    for path, problem in problems:
        click.echo(f"{path}: {problem}")
    finish_batch(report)
    if problems:
        raise click.exceptions.Exit(1)


@click.command("img-duplicates")
@hash_options
@click.option(
    "--max-distance",
    type=click.IntRange(min=0),
    default=8,
    show_default=True,
    help="bits two hashes may differ in and still be duplicates",
)
@click.option(
    "-x",
    "--command",
    default=None,
    help="run this command once per group, with the group's files appended",
)
def img_duplicates_cmd(
    paths: tuple[Path, ...],
    hash_size: int,
    no_cache: bool,
    max_distance: int,
    command: str | None,
) -> None:
    """Find groups of near-duplicate images in PATH..."""
    imghash = load_imghash()
    hasher = imghash.ImageHasher(
        hash_size, hash_cache(no_cache, imghash.CACHE_EXPIRATION)
    )
    hashes: list[tuple[Path, str]] = []

    def collect(path: Path, _reporter: BaseProgressReporter) -> None:
        hashes.append((path, hasher.hash(path)))

    report = run_batch(
        expand_inputs(paths, media.is_image), collect, description="Hashing"
    )
    groups = imghash.duplicate_groups(hashes, max_distance)
    if not groups:
        click.echo("no duplicates found")
    for number, group in enumerate(groups, start=1):
        if command is None:
            click.echo(f"group {number}")
            for path in group:
                click.echo(f"  {path}")
            continue
        try:
            run_command_with_paths(shlex.split(command), group)
        except JOB_ERRORS as exc:
            raise click.ClickException(str(exc)) from exc
    finish_batch(report)
