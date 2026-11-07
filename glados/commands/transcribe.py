"""`glados transcribe` and the standalone `transcribe` tool: video/audio ->
subtitle/text sidecar via a Transcriber backend (steps in
glados/tasks/transcribe.py).

The Transcriber backend is selected and loaded by core/backends.py;
-m/--model overrides its global `model` option, while --language and
--format are per-run arguments. The same click.Command is the `glados`
subcommand (cli.py adds it to the group) and the standalone tool
(pyproject.toml's [project.scripts] points straight at it).
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    check_single_output,
    common_file_options,
    dry_run_option,
    job_action,
    paths_argument,
    print_plan,
    run_jobs,
)
from filejobs.inputs import expand_inputs, media_type_filter
from filejobs.pipeline import Job, override_destination, suffix_destination
from glados.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_glados,
)
from glados.core.session import Glados
from glados.tasks.protocols import Transcriber
from glados.tasks.transcribe import (
    DEFAULT_OUTPUT_FORMAT,
    FORMATTERS,
    AudioExtractor,
    TranscribeStep,
)


def resolve_output_format(requested: str | None, output: Path | None) -> str:
    """The -f/--format value if given; otherwise the -o/--output extension
    when it names a known format (so `-o talk.srt` writes SRT); otherwise
    DEFAULT_OUTPUT_FORMAT."""
    if requested is not None:
        return requested
    if output is not None:
        extension = output.suffix.removeprefix(".").lower()
        if extension in FORMATTERS:
            return extension
    return DEFAULT_OUTPUT_FORMAT


@click.command("transcribe")
@paths_argument
@model_option
@click.option(
    "-l",
    "--language",
    default=None,
    help="audio language code, e.g. en, es (default: auto-detect)",
)
@click.option(
    "-f",
    "--format",
    "output_format",
    type=click.Choice(sorted(FORMATTERS)),
    default=None,
    help=(
        "output format (default: the -o extension if it is a known format,"
        f" else {DEFAULT_OUTPUT_FORMAT})"
    ),
)
@backend_option("transcribe")
@common_file_options
@dry_run_option
@logging_options
@pass_glados
def cli(
    glados: Glados,
    paths: tuple[Path, ...],
    model: str | None,
    language: str | None,
    output_format: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Extract audio and transcribe each input in PATH... to a plain-text or subtitle sidecar."""
    inputs = expand_inputs(paths, media_type_filter("audio/", "video/"))
    check_single_output(output, inputs)
    output_format = resolve_output_format(output_format, output)
    dest_fn = override_destination(output, suffix_destination(output_format))
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    transcriber = glados.backend("transcribe", Transcriber, backend, {"model": model})
    job = Job(
        steps=[
            (AudioExtractor(), "Extracting audio"),
            (
                TranscribeStep(
                    transcriber, language=language, output_format=output_format
                ),
                "Transcribing",
            ),
        ],
        dest_fn=dest_fn,
    )
    run_jobs(inputs, job_action(job, overwrite), "Transcribing")


if __name__ == "__main__":
    cli()
