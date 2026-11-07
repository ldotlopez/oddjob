"""`oddjob img-embed-description`: one in-place Job per image, describing it
first when it has no NAME.description.txt (or with --redescribe)."""

from __future__ import annotations

import contextlib
from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    dry_run_option,
    overwrite_option,
    paths_argument,
    require_overwrite,
    run_jobs,
)
from filejobs.inputs import expand_inputs
from filejobs.pipeline import Job
from filejobs.progress import BaseProgressReporter
from oddjob.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_session,
)
from oddjob.core.describing import describe_prompt, open_describer
from oddjob.core.session import Session
from oddjob.lib import media
from oddjob.lib.captions import Caption, CaptionStep, plan_captions
from oddjob.lib.describe import DescribeStep
from oddjob.lib.external import ExifTool
from oddjob.lib.protocols import Describer


@click.command("img-embed-description")
@paths_argument
@click.option(
    "--redescribe",
    is_flag=True,
    default=False,
    help="describe every image again, replacing its NAME.description.txt",
)
@click.option(
    "-l",
    "--language",
    default=None,
    help="language of generated descriptions (default: the system locale's)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="neither read nor store cached descriptions",
)
@model_option
@backend_option("describe")
@overwrite_option
@dry_run_option
@logging_options
@pass_session
def img_embed_description_cmd(
    session: Session,
    paths: tuple[Path, ...],
    redescribe: bool,
    language: str | None,
    no_cache: bool,
    model: str | None,
    backend: str | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Write each image's NAME.description.txt into its XMP and EXIF
    description, in place (needs -y). An image without that file is first
    described with `oddjob describe` (needs a model that takes images), which
    writes it; --redescribe does so for every image."""
    if not dry_run:
        require_overwrite(overwrite, "img-embed-description rewrites images in place")
    captions = plan_captions(
        expand_inputs(paths, media.is_image), redescribe=redescribe
    )
    if dry_run:
        for caption in captions:
            click.echo(caption.describe())
        return
    try:
        exiftool = ExifTool()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    with contextlib.ExitStack() as stack:
        describer: Describer | None = None
        prompt = ""
        if any(caption.generate for caption in captions):
            prompt = describe_prompt(session, None, language)
            describer = open_describer(
                stack, session, backend, model, use_cache=not no_cache
            )

        def apply(caption: Caption, reporter: BaseProgressReporter) -> Path:
            if caption.generate and describer is not None:
                Job(
                    steps=[(DescribeStep(describer, prompt), "Describing")],
                    dest_fn=lambda _image: caption.sidecar,
                ).run(caption.image, reporter, overwrite=redescribe)
            step = CaptionStep(exiftool, caption.text())
            job = Job(
                steps=[(step, f"Embedding {caption.image.name}")],
                dest_fn=lambda _image: caption.image,
            )
            return job.run(caption.image, reporter, overwrite=overwrite)

        run_jobs(captions, apply, "Embedding", label=lambda caption: str(caption.image))
