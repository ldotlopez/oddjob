"""Tag command: print the kind, a short description and hashtags of each
file in PATH..., of `--text` or of stdin (logic in oddjob/lib/tag.py).

No backend of its own: it uses the backends selected for rewrite, describe
and transcribe (core/tagging.py), with tag's prompt from `[prompts] tag`,
replying in -l/--language or else the system locale's. Audio and video are
transcribed only up to --max-duration seconds unless --full-audio. Results
are cached (oddjob/lib/cache.py); --no-cache skips it. A report under
run_batch: it writes no file, so it takes no -n, -o or -y.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import replace
from pathlib import Path

import rich_click as click

from filejobs.batch import run_batch
from filejobs.cli_options import finish_batch
from filejobs.inputs import accept_all, expand_inputs
from filejobs.progress import BaseProgressReporter
from oddjob.core.cache import open_user_cache
from oddjob.core.cli_common import logging_options, pass_session
from oddjob.core.session import Session
from oddjob.core.tagging import SessionBackends, tag_prompt
from oddjob.lib.speak import FileSource, SourceError, choose_source
from oddjob.lib.tag import ContentKind, Tagger, TagResult
from oddjob.lib.transcribe import AudioExtractor

DEFAULT_MAX_DURATION = 60.0


def format_line(label: str, result: TagResult) -> str:
    return " ".join(
        [f"{label}: {result.kind.value} ·", result.description, *result.hashtags]
    )


def format_json(path: Path | None, result: TagResult) -> str:
    value = {
        "path": None if path is None else str(path),
        "type": result.kind.value,
        "description": result.description,
        "hashtags": list(result.hashtags),
    }
    return json.dumps(value, ensure_ascii=False)


@click.command("tag")
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path, allow_dash=True),
)
@click.option(
    "-t", "--text", default=None, help="text to tag, instead of PATH... or stdin"
)
@click.option(
    "--context",
    default=None,
    help="text that comes with the content, e.g. a caption or a post's title",
)
@click.option(
    "--type",
    "forced_kind",
    type=click.Choice([kind.value for kind in ContentKind]),
    default=None,
    help="report this type instead of the detected one (the content is"
    " still handled as detected)",
)
@click.option(
    "-l",
    "--language",
    default=None,
    help="language of the description and hashtags, e.g. 'es'"
    " (default: the system locale's)",
)
@click.option(
    "--max-duration",
    type=click.FloatRange(min=0, min_open=True),
    default=None,
    help=f"seconds of audio/video to transcribe (default: {DEFAULT_MAX_DURATION:g})",
)
@click.option(
    "--full-audio",
    is_flag=True,
    default=False,
    help="transcribe the whole audio/video (excludes --max-duration)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="print one JSON object per input (path, type, description, hashtags)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="neither read nor store cached results",
)
@logging_options
@pass_session
def tag_cmd(
    session: Session,
    paths: tuple[Path, ...],
    text: str | None,
    context: str | None,
    forced_kind: str | None,
    language: str | None,
    max_duration: float | None,
    full_audio: bool,
    as_json: bool,
    no_cache: bool,
) -> None:
    """Print the type, a short description and hashtags of each file in
    PATH..., of `--text`, or of stdin (`-`, or a pipe), as
    `PATH: type · description #tag ...`. Uses the rewrite, describe and
    transcribe backends."""
    if full_audio and max_duration is not None:
        raise click.UsageError("--full-audio and --max-duration exclude each other")
    stdin = click.get_text_stream("stdin")
    try:
        source = choose_source(
            paths, text, None, stdin_is_terminal=stdin.isatty(), needs_output=False
        )
    except SourceError as exc:
        raise click.UsageError(str(exc)) from exc
    if full_audio:
        limit = None
    else:
        limit = DEFAULT_MAX_DURATION if max_duration is None else max_duration

    results: list[tuple[str, Path | None, TagResult]] = []
    with contextlib.ExitStack() as stack:
        tagger = Tagger(
            SessionBackends(session),
            tag_prompt(session, language),
            store=None if no_cache else stack.enter_context(open_user_cache()),
            max_duration=limit,
            extractor=lambda: AudioExtractor(max_duration=limit),
        )
        if isinstance(source, FileSource):

            def tag_file(path: Path, reporter: BaseProgressReporter) -> None:
                results.append(
                    (str(path), path, tagger.tag_file(path, context, reporter))
                )

            report = run_batch(
                expand_inputs(source.paths, accept_all), tag_file, description="Tagging"
            )
        else:
            label = "stdin" if source.text is None else "text"
            content = stdin.read() if source.text is None else source.text
            if not content.strip():
                raise click.UsageError("stdin is empty")

            def tag_text(_: str, reporter: BaseProgressReporter) -> None:
                results.append(
                    (label, None, tagger.tag_text(content, context, reporter))
                )

            report = run_batch([label], tag_text, description="Tagging")

    for label, path, result in results:
        if forced_kind is not None:
            result = replace(result, kind=ContentKind(forced_kind))
        click.echo(format_json(path, result) if as_json else format_line(label, result))
    finish_batch(report)


if __name__ == "__main__":
    tag_cmd()
