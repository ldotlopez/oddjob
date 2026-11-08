"""`oddjob motionphotos`: check, join, split, strip and merge.

Every command that writes a file runs a Job with a BytesStep, so results
land through the same temp-file -> destination flow as oddjob's tasks.
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    dry_run_option,
    keep_mtime_option,
    overwrite_option,
    paths_argument,
    require_overwrite,
    run_jobs,
    run_single_job,
)
from filejobs.inputs import accept_all, expand_inputs
from filejobs.pipeline import JOB_ERRORS, BytesStep, Job, check_destination
from filejobs.progress import BaseProgressReporter
from oddjob.core.cli_common import logging_options
from oddjob.lib import motionphotos, sidecars

existing_file = click.Path(exists=True, dir_okay=False, path_type=Path)


def to_destination(
    step: BytesStep, description: str, destination: Path, keep_mtime: bool
) -> Job:
    return Job(
        steps=[(step, description)],
        dest_fn=lambda _input: destination,
        keep_times=keep_mtime,
    )


def joining_step(video: Path) -> BytesStep:
    return BytesStep(lambda image: motionphotos.join(image, video.read_bytes()))


@click.group("motionphotos")
def motionphotos_cmd() -> None:
    """Check, join, split, strip and merge motion photos."""


@motionphotos_cmd.command("check")
@click.argument("file", type=existing_file)
@logging_options
def check_cmd(file: Path) -> None:
    """Exit 0 if FILE is a motion photo, 1 if not."""
    try:
        photo = motionphotos.MotionPhoto.parse(file.read_bytes())
    except JOB_ERRORS as exc:
        raise click.ClickException(str(exc)) from exc
    if photo.video is None:
        click.echo(f"{file}: not a motion photo")
        raise click.exceptions.Exit(1)
    click.echo(f"{file}: motion photo")


@motionphotos_cmd.command("join")
@click.option("-i", "--image", required=True, type=existing_file)
@click.option("--video", required=True, type=existing_file)
@click.option("-o", "--output", required=True, type=click.Path(path_type=Path))
@overwrite_option
@keep_mtime_option
@click.option("--rm", "remove_video", is_flag=True, help="remove VIDEO afterwards")
@logging_options
def join_cmd(
    image: Path,
    video: Path,
    output: Path,
    overwrite: bool,
    keep_mtime: bool,
    remove_video: bool,
) -> None:
    """Join IMAGE and VIDEO into the motion photo OUTPUT."""
    job = to_destination(joining_step(video), "Joining", output, keep_mtime)
    run_single_job(job, image, overwrite)
    if remove_video:
        video.unlink()


@motionphotos_cmd.command("split")
@click.argument("file", type=existing_file)
@click.option("-i", "--image", required=True, type=click.Path(path_type=Path))
@click.option("--video", required=True, type=click.Path(path_type=Path))
@overwrite_option
@keep_mtime_option
@logging_options
def split_cmd(
    file: Path, image: Path, video: Path, overwrite: bool, keep_mtime: bool
) -> None:
    """Split motion photo FILE into IMAGE and VIDEO."""
    for destination in (image, video):
        try:
            check_destination(destination, overwrite)
        except FileExistsError as exc:
            raise click.ClickException(str(exc)) from exc
    still = BytesStep(lambda content: motionphotos.split(content)[0], image.suffix)
    clip = BytesStep(lambda content: motionphotos.split(content)[1], video.suffix)
    run_single_job(
        to_destination(still, "Extracting image", image, keep_mtime), file, overwrite
    )
    run_single_job(
        to_destination(clip, "Extracting video", video, keep_mtime), file, overwrite
    )


@motionphotos_cmd.command("strip")
@click.argument("file", type=existing_file)
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), help="default: FILE itself"
)
@overwrite_option
@keep_mtime_option
@logging_options
def strip_cmd(
    file: Path, output: Path | None, overwrite: bool, keep_mtime: bool
) -> None:
    """Remove the video of motion photo FILE (in place needs -y)."""
    if output is None:
        require_overwrite(overwrite, "strip without -o rewrites FILE in place")
    job = to_destination(
        BytesStep(motionphotos.strip), "Stripping", output or file, keep_mtime
    )
    run_single_job(job, file, overwrite)


@motionphotos_cmd.command("merge")
@paths_argument
@click.option("--rm", "remove_video", is_flag=True, help="remove each merged video")
@overwrite_option
@keep_mtime_option
@dry_run_option
@logging_options
def merge_cmd(
    paths: tuple[Path, ...],
    remove_video: bool,
    overwrite: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Merge each NAME.jpg + NAME.mp4 pair in PATH... into NAME.jpg, in
    place (needs -y)."""
    if not dry_run:
        require_overwrite(overwrite, "merge rewrites each NAME.jpg in place")
    groups = sidecars.group_sidecars(expand_inputs(paths, accept_all))
    merges = motionphotos.plan_merges(groups, remove_video)
    if dry_run:
        for merge in merges:
            click.echo(merge.describe())
        return

    def apply(merge: motionphotos.Merge, reporter: BaseProgressReporter) -> Path:
        description = f"Merging {merge.image.name}"
        job = to_destination(
            joining_step(merge.video), description, merge.image, keep_mtime
        )
        written = job.run(merge.image, reporter, overwrite=overwrite)
        if merge.remove_video:
            merge.video.unlink()
        return written

    run_jobs(merges, apply, "Merging", label=lambda merge: str(merge.image))
