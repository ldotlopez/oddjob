"""`multitool jpgize` and `multitool mp4ize`: one Job per input file."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import rich_click as click

from glados.core.cli_options import (
    dry_run_option,
    overwrite_option,
    paths_argument,
    run_jobs,
)
from glados.core.inputs import expand_inputs
from glados.core.pipeline import ProgressStep
from glados.core.progress import BaseProgressReporter
from glados.core.runners import FFMpegRunner
from multitool import media
from multitool.conversions import (
    Conversion,
    JpegConversionStep,
    Mp4RemuxStep,
    plan_conversions,
    run_conversion,
)
from multitool.external import ExifTool, ImageMagick


def conversion_options[F: Callable[..., object]](func: F) -> F:
    func = dry_run_option(func)
    func = click.option(
        "--rm", "remove_source", is_flag=True, help="remove each converted source"
    )(func)
    func = overwrite_option(func)
    return paths_argument(func)


def convert_all(
    conversions: Sequence[Conversion],
    build_step: Callable[[], ProgressStep[Path]],
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Print the plan, or build the step (adapters checked once) and run one
    Job per conversion."""
    if dry_run:
        for conversion in conversions:
            click.echo(conversion.describe())
        return
    try:
        step = build_step()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    def convert(conversion: Conversion, reporter: BaseProgressReporter) -> Path:
        return run_conversion(conversion, step, reporter, overwrite=overwrite)

    run_jobs(
        conversions,
        convert,
        "Converting",
        label=lambda conversion: str(conversion.source),
    )


@click.command("jpgize")
@conversion_options
def jpgize_cmd(
    paths: tuple[Path, ...], overwrite: bool, remove_source: bool, dry_run: bool
) -> None:
    """Convert HEIC/HEIF/WebP/PNG images in PATH... to JPEG, keeping metadata."""
    conversions = plan_conversions(
        expand_inputs(paths, media.converts_to_jpeg), "jpg", remove_source
    )
    convert_all(
        conversions,
        lambda: JpegConversionStep(ImageMagick(), ExifTool()),
        overwrite,
        dry_run,
    )


@click.command("mp4ize")
@conversion_options
def mp4ize_cmd(
    paths: tuple[Path, ...], overwrite: bool, remove_source: bool, dry_run: bool
) -> None:
    """Remux videos in PATH... into MP4 without re-encoding the video."""
    conversions = plan_conversions(
        expand_inputs(paths, media.converts_to_mp4), "mp4", remove_source
    )
    convert_all(conversions, lambda: Mp4RemuxStep(FFMpegRunner()), overwrite, dry_run)
