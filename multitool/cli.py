"""`multitool` entry point: file utilities without the backend registry.

Commands only parse options, expand inputs, wire adapters and call the
multitool modules; see docs/decisions/0003. Commands taking PATH... walk
directories recursively, keep going when one input fails and exit 1 if any
did. Commands that change files take -n/--dry-run.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import rich_click as click
from foundation.cache import UserCache

from glados.core.batch import INPUT_ERRORS, run_batch
from glados.core.cli_options import (
    dry_run_option,
    finish_batch,
    logging_options_for,
    overwrite_option,
    paths_argument,
)
from glados.core.inputs import accept_all, expand_inputs
from glados.core.runners import FFMpegRunner
from multitool import media, motionphotos, renamers, sidecars
from multitool.conversions import (
    Conversion,
    convert_to_jpeg,
    plan_conversions,
    remux_to_mp4,
)
from multitool.external import ExifTool, ImageMagick, run_command_with_paths
from multitool.files import write_into_place

APP_LOGGER = "multitool"


@contextmanager
def input_errors_as_click_errors() -> Iterator[None]:
    """For single-file commands: a failure becomes a clean error message."""
    try:
        yield
    except INPUT_ERRORS as exc:
        raise click.ClickException(str(exc)) from exc


def print_plan(descriptions: Sequence[str]) -> None:
    for description in descriptions:
        click.echo(description)


@click.group()
@logging_options_for(APP_LOGGER)
def cli() -> None:
    """File utilities: sidecars, motion photos, conversions, image hashes,
    renames."""


# --- sidecars -------------------------------------------------------------


@cli.group("sidecars")
def sidecars_cmd() -> None:
    """Scan and search for sidecar files."""


@sidecars_cmd.command("scan")
@paths_argument
@click.option(
    "-e",
    "--extension",
    "extensions",
    multiple=True,
    help="only groups having all these extensions (at least two)",
)
@click.option(
    "--cs", "case_sensitive", is_flag=True, help="match extensions case-sensitively"
)
def sidecars_scan_cmd(
    paths: tuple[Path, ...], extensions: tuple[str, ...], case_sensitive: bool
) -> None:
    """List groups of files sharing a name in PATH..."""
    if len(extensions) == 1:
        raise click.UsageError("give at least two extensions")
    groups = sidecars.group_sidecars(expand_inputs(paths, accept_all))
    if extensions:
        groups = sidecars.with_extensions(groups, extensions, case_sensitive)
    for group in groups:
        click.echo(f"{group.base}")
        for file in group.files:
            click.echo(f"  {sidecars.extension_of(file, case_sensitive)}: {file}")


@sidecars_cmd.command("find")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def sidecars_find_cmd(file: Path) -> None:
    """List the sidecar files of FILE."""
    group = sidecars.sidecars_of(file, file.parent.iterdir())
    if group is None:
        click.echo("no sidecar files found")
        return
    for member in group.files:
        click.echo(str(member))


# --- motionphotos ---------------------------------------------------------


@cli.group("motionphotos")
def motionphotos_cmd() -> None:
    """Check, join, split, strip and merge motion photos."""


@motionphotos_cmd.command("check")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def motionphotos_check_cmd(file: Path) -> None:
    """Exit 0 if FILE is a motion photo, 1 if not."""
    with input_errors_as_click_errors():
        photo = motionphotos.MotionPhoto.parse(file.read_bytes())
    if photo.video is None:
        click.echo(f"{file}: not a motion photo")
        raise click.exceptions.Exit(1)
    click.echo(f"{file}: motion photo")


@motionphotos_cmd.command("join")
@click.option(
    "-i", "--image", required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option(
    "-v", "--video", required=True, type=click.Path(exists=True, path_type=Path)
)
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path))
@overwrite_option
@click.option("--rm", "remove_video", is_flag=True, help="remove VIDEO afterwards")
def motionphotos_join_cmd(
    image: Path, video: Path, output: Path, overwrite: bool, remove_video: bool
) -> None:
    """Join IMAGE and VIDEO into the motion photo OUTPUT."""
    with input_errors_as_click_errors():
        content = motionphotos.join(image.read_bytes(), video.read_bytes())
        write_into_place(content, output, overwrite=overwrite, stat_source=image)
        if remove_video:
            video.unlink()


@motionphotos_cmd.command("split")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-i", "--image", required=True, type=click.Path(path_type=Path))
@click.option("-v", "--video", required=True, type=click.Path(path_type=Path))
@overwrite_option
def motionphotos_split_cmd(
    file: Path, image: Path, video: Path, overwrite: bool
) -> None:
    """Split motion photo FILE into IMAGE and VIDEO."""
    with input_errors_as_click_errors():
        still, clip = motionphotos.split(file.read_bytes())
        write_into_place(still, image, overwrite=overwrite, stat_source=file)
        write_into_place(clip, video, overwrite=overwrite, stat_source=file)


@motionphotos_cmd.command("strip")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), help="default: FILE itself"
)
@overwrite_option
def motionphotos_strip_cmd(file: Path, output: Path | None, overwrite: bool) -> None:
    """Remove the video of motion photo FILE (in place needs -y)."""
    with input_errors_as_click_errors():
        content = motionphotos.strip(file.read_bytes())
        write_into_place(content, output or file, overwrite=overwrite, stat_source=file)


@motionphotos_cmd.command("merge")
@paths_argument
@click.option("--rm", "remove_video", is_flag=True, help="remove each merged video")
@dry_run_option
def motionphotos_merge_cmd(
    paths: tuple[Path, ...], remove_video: bool, dry_run: bool
) -> None:
    """Merge each NAME.jpg + NAME.mp4 pair in PATH... into NAME.jpg."""
    groups = sidecars.group_sidecars(expand_inputs(paths, accept_all))
    merges = motionphotos.plan_merges(groups, remove_video)
    if dry_run:
        print_plan([merge.describe() for merge in merges])
        return

    def apply(merge: motionphotos.Merge) -> None:
        content = motionphotos.join(merge.image.read_bytes(), merge.video.read_bytes())
        write_into_place(content, merge.image, overwrite=True, stat_source=merge.image)
        if merge.remove_video:
            merge.video.unlink()

    finish_batch(
        run_batch(
            merges, apply, description="Merging", label=lambda merge: str(merge.image)
        )
    )


# --- conversions ----------------------------------------------------------


def run_conversions(
    paths: Sequence[Path],
    accepts: Callable[[Path], bool],
    extension: str,
    remove_source: bool,
    dry_run: bool,
    convert: Callable[[Conversion], None],
    description: str,
) -> None:
    conversions = plan_conversions(
        expand_inputs(paths, accepts), extension, remove_source
    )
    if dry_run:
        print_plan([conversion.describe() for conversion in conversions])
        return
    finish_batch(
        run_batch(
            conversions,
            convert,
            description=description,
            label=lambda conversion: str(conversion.source),
        )
    )


def remove_source_option[F: Callable[..., object]](func: F) -> F:
    return click.option(
        "--rm", "remove_source", is_flag=True, help="remove each converted source"
    )(func)


@cli.command("jpgize")
@paths_argument
@overwrite_option
@remove_source_option
@dry_run_option
def jpgize_cmd(
    paths: tuple[Path, ...], overwrite: bool, remove_source: bool, dry_run: bool
) -> None:
    """Convert HEIC/HEIF/WebP/PNG images in PATH... to JPEG, keeping metadata."""
    magick = None if dry_run else ImageMagick()
    exiftool = None if dry_run else ExifTool()

    def convert(conversion: Conversion) -> None:
        assert magick is not None and exiftool is not None
        convert_to_jpeg(conversion, magick, exiftool, overwrite=overwrite)

    run_conversions(
        paths,
        media.converts_to_jpeg,
        ".jpg",
        remove_source,
        dry_run,
        convert,
        "Converting",
    )


@cli.command("mp4ize")
@paths_argument
@overwrite_option
@remove_source_option
@dry_run_option
def mp4ize_cmd(
    paths: tuple[Path, ...], overwrite: bool, remove_source: bool, dry_run: bool
) -> None:
    """Remux videos in PATH... into MP4 without re-encoding the video."""
    ffmpeg = None if dry_run else FFMpegRunner()

    def convert(conversion: Conversion) -> None:
        assert ffmpeg is not None
        remux_to_mp4(conversion, ffmpeg, overwrite=overwrite)

    run_conversions(
        paths,
        media.converts_to_mp4,
        ".mp4",
        remove_source,
        dry_run,
        convert,
        "Remuxing",
    )


# --- image hashes ---------------------------------------------------------


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


def hash_size_option[F: Callable[..., object]](func: F) -> F:
    return click.option(
        "--hash-size",
        type=click.IntRange(min=2),
        default=16,
        show_default=True,
        help="hash side in pixels (bits = size²)",
    )(func)


def no_cache_option[F: Callable[..., object]](func: F) -> F:
    return click.option(
        "--no-cache", is_flag=True, help="neither read nor store cached hashes"
    )(func)


def hash_cache(no_cache: bool, expiration: float) -> UserCache | None:
    """The hash cache, closed when the running command ends."""
    if no_cache:
        return None
    cache = UserCache(app=APP_LOGGER, expiration_time=expiration)
    click.get_current_context().call_on_close(cache.close)
    return cache


@cli.command("img-hash")
@paths_argument
@hash_size_option
@no_cache_option
def img_hash_cmd(paths: tuple[Path, ...], hash_size: int, no_cache: bool) -> None:
    """Print the average hash of each image in PATH..."""
    imghash = load_imghash()
    hasher = imghash.ImageHasher(
        hash_size, hash_cache(no_cache, imghash.CACHE_EXPIRATION)
    )

    def show(path: Path) -> None:
        click.echo(f"{path}: {hasher.hash(path)}")

    finish_batch(
        run_batch(expand_inputs(paths, media.is_image), show, description="Hashing")
    )


@cli.command("img-duplicates")
@paths_argument
@hash_size_option
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
@no_cache_option
def img_duplicates_cmd(
    paths: tuple[Path, ...],
    hash_size: int,
    max_distance: int,
    command: str | None,
    no_cache: bool,
) -> None:
    """Find groups of near-duplicate images in PATH..."""
    imghash = load_imghash()
    hasher = imghash.ImageHasher(
        hash_size, hash_cache(no_cache, imghash.CACHE_EXPIRATION)
    )
    hashes: list[tuple[Path, str]] = []

    def collect(path: Path) -> None:
        hashes.append((path, hasher.hash(path)))

    report = run_batch(
        expand_inputs(paths, media.is_image), collect, description="Hashing"
    )
    groups = imghash.duplicate_groups(hashes, max_distance)
    if not groups:
        click.echo("no duplicates found")
    for number, group in enumerate(groups, start=1):
        if command:
            with input_errors_as_click_errors():
                run_command_with_paths(shlex.split(command), group)
            continue
        click.echo(f"group {number}")
        for path in group:
            click.echo(f"  {path}")
    finish_batch(report)


# --- renames --------------------------------------------------------------


@cli.command("hash-rename")
@paths_argument
@click.option(
    "--algo",
    type=click.Choice(renamers.digest_algorithms()),
    default=renamers.DEFAULT_ALGORITHM,
    show_default=True,
)
@overwrite_option
@dry_run_option
def hash_rename_cmd(
    paths: tuple[Path, ...], algo: str, overwrite: bool, dry_run: bool
) -> None:
    """Rename each file in PATH... to <digest of its content>.<ext>."""

    def rename(path: Path) -> None:
        planned = renamers.plan_rename(path, renamers.file_digest(path, algo))
        if planned is None:
            return
        if dry_run:
            click.echo(planned.describe())
        else:
            renamers.apply_rename(planned, overwrite)

    finish_batch(
        run_batch(expand_inputs(paths, accept_all), rename, description="Renaming")
    )


if __name__ == "__main__":
    cli()
