"""`glados audio-grep` and the standalone `audio-grep` tool: grep over the
transcriptions of audio/video files (logic in glados/tasks/audio_grep.py).

Every argument that is not one of the options below, an existing directory
or an audio/video file goes to grep unchanged, so the options are long-only:
grep owns nearly every short flag (-b, -m, -l, -v, -q, ...). Transcripts are
cached in the user cache directory, never written as sidecars.
"""

from __future__ import annotations

from pathlib import Path

import platformdirs
import rich_click as click
from foundation.cache import UserCache

from filejobs.batch import run_batch
from filejobs.cli_options import setup_logging
from filejobs.inputs import expand_inputs, media_type_filter
from filejobs.progress import BaseProgressReporter
from glados.core.cli_common import APP_LOGGER, pass_glados
from glados.core.session import Glados
from glados.lib.audio_grep import (
    DEFAULT_TRANSCRIPT_FORMAT,
    TRANSCRIPT_TTL,
    CachedTranscripts,
    Transcript,
    TranscriptionSettings,
    grep_transcripts,
    split_command_line,
)
from glados.lib.grep import GrepRunner
from glados.lib.protocols import Transcriber
from glados.lib.transcribe import FORMATTERS

CACHE_APP = "glados"
# grep's exit status for an error; a failed transcription counts as one.
GREP_ERROR = 2

is_media = media_type_filter("audio/", "video/")


@click.command(
    "audio-grep",
    context_settings={"ignore_unknown_options": True},
)
@click.argument("arguments", nargs=-1, required=True, type=click.UNPROCESSED)
@click.option(
    "--backend",
    default=None,
    envvar="GLADOS_TRANSCRIBE_BACKEND",
    show_envvar=True,
    help="transcribe backend (default: [tasks] transcribe in the config,"
    " or the only one installed)",
)
@click.option(
    "--model",
    default=None,
    help="model file/name, overriding [backends.<name>] model",
)
@click.option(
    "--language",
    default=None,
    help="audio language code, e.g. en, es (default: auto-detect)",
)
@click.option(
    "--transcript-format",
    type=click.Choice(sorted(FORMATTERS)),
    default=DEFAULT_TRANSCRIPT_FORMAT,
    show_default=True,
    help="what grep searches; lrc is one timestamped line per segment",
)
@click.option(
    "--log-level",
    default=None,
    help="e.g. debug or glados.core:debug,*:info (also GLADOS_LOG_LEVEL)",
)
@pass_glados
def cli(
    glados: Glados,
    arguments: tuple[str, ...],
    backend: str | None,
    model: str | None,
    language: str | None,
    transcript_format: str,
    log_level: str | None,
) -> None:
    """grep [OPTIONS] PATTERNS over the transcriptions of the audio/video
    files and directories among ARGUMENTS; grep's output names the media
    files. Exit status as grep's, or 2 if a file could not be transcribed.
    A pattern starting with `-` needs `-e`."""
    setup_logging(APP_LOGGER, log_level, verbose=0, quiet=0)
    command_line = split_command_line(arguments, is_media)
    if not command_line.paths:
        raise click.UsageError("no audio/video file or directory among the arguments")
    try:
        grep = GrepRunner()
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    def make_transcriber() -> Transcriber:
        return glados.backend("transcribe", Transcriber, backend, {"model": model})

    transcripts: list[Transcript] = []
    cache_dir = Path(platformdirs.user_cache_dir(CACHE_APP)) / "transcripts"
    with UserCache(
        app=CACHE_APP, expiration_time=TRANSCRIPT_TTL, base_dir=cache_dir
    ) as cache:
        source = CachedTranscripts(
            cache, make_transcriber, TranscriptionSettings(backend, model, language)
        )

        def load(media: Path, reporter: BaseProgressReporter) -> None:
            transcripts.append(Transcript(media, source.segments(media, reporter)))

        report = run_batch(
            expand_inputs(command_line.paths, is_media),
            load,
            description="Transcribing",
        )

    status = 1  # grep's "nothing matched", also when there is nothing to search
    if transcripts:
        result = grep_transcripts(
            grep, command_line.grep_args, transcripts, transcript_format
        )
        click.get_binary_stream("stdout").write(result.stdout)
        click.get_binary_stream("stderr").write(result.stderr)
        status = result.returncode
    if report.failures:
        status = GREP_ERROR
    raise click.exceptions.Exit(status)


if __name__ == "__main__":
    cli()
