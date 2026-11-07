"""`multitool img-caption`: one in-place Job per image with a description."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    dry_run_option,
    overwrite_option,
    paths_argument,
    run_jobs,
)
from filejobs.inputs import expand_inputs
from filejobs.pipeline import Job
from filejobs.progress import BaseProgressReporter
from glados.lib import media
from glados.lib.captions import Caption, CaptionStep, plan_captions
from glados.lib.external import ExifTool


@click.command("img-caption")
@paths_argument
@overwrite_option
@dry_run_option
def img_caption_cmd(paths: tuple[Path, ...], overwrite: bool, dry_run: bool) -> None:
    """Write each image's NAME.description.txt (from `glados describe`) into
    its XMP and EXIF description, in place (needs -y). Images in directories
    without one are skipped."""
    captions = plan_captions(expand_inputs(paths, media.is_image), set(paths))
    if dry_run:
        for caption in captions:
            click.echo(caption.describe())
        return
    try:
        exiftool = ExifTool()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    def apply(caption: Caption, reporter: BaseProgressReporter) -> Path:
        step = CaptionStep(exiftool, caption.text())
        job = Job(
            steps=[(step, f"Captioning {caption.image.name}")],
            dest_fn=lambda _image: caption.image,
        )
        return job.run(caption.image, reporter, overwrite=overwrite)

    run_jobs(captions, apply, "Captioning", label=lambda caption: str(caption.image))
