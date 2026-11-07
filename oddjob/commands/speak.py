"""Speak command: text -> WAV audio via a Speaker backend.

The text comes from text files (PATH...), `--text` or stdin (`-`, or a pipe
when nothing else is given); lib/speak.py decides which. Files land at
suffix_destination("wav"), so note.txt -> note.wav; a literal or piped text
has no name to derive one from and needs -o. The Speaker backend is
selected and loaded by core/backends.py.
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    check_single_output,
    common_file_options,
    dry_run_option,
    job_action,
    print_plan,
    run_jobs,
)
from filejobs.inputs import expand_inputs, media_type_filter
from filejobs.pipeline import Job, override_destination, suffix_destination
from oddjob.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_session,
)
from oddjob.core.session import Session
from oddjob.lib.protocols import Speaker
from oddjob.lib.speak import (
    AUDIO_EXTENSION,
    FileSource,
    SourceError,
    SpeakStep,
    choose_source,
    describe_text,
    staged_text,
)


@click.command("speak")
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path, allow_dash=True),
)
@click.option(
    "-t",
    "--text",
    default=None,
    help="text to speak, instead of PATH... (needs -o)",
)
@click.option(
    "--speaker",
    type=int,
    default=None,
    help="speaker number of a multi-speaker voice (default: the voice's own)",
)
@model_option
@backend_option("speak")
@common_file_options
@dry_run_option
@logging_options
@pass_session
def speak_cmd(
    session: Session,
    paths: tuple[Path, ...],
    text: str | None,
    speaker: int | None,
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Speak each text file in PATH..., `--text` or stdin (`-`, or a pipe) as WAV audio."""
    stdin = click.get_text_stream("stdin")
    try:
        source = choose_source(paths, text, output, stdin_is_terminal=stdin.isatty())
    except SourceError as exc:
        raise click.UsageError(str(exc)) from exc

    dest_fn = override_destination(output, suffix_destination(AUDIO_EXTENSION))
    inputs: list[Path] = []
    if isinstance(source, FileSource):
        inputs = expand_inputs(source.paths, media_type_filter("text/"))
        check_single_output(output, inputs)
    if dry_run:
        if isinstance(source, FileSource):
            print_plan(inputs, dest_fn)
        else:
            shown = "-" if source.text is None else describe_text(source.text)
            click.echo(f"{shown} -> {output}")
        return

    speaker_backend = session.backend("speak", Speaker, backend, {"model": model})
    job = Job(
        steps=[(SpeakStep(speaker_backend, speaker), "Speaking")], dest_fn=dest_fn
    )
    action = job_action(job, overwrite)
    if isinstance(source, FileSource):
        run_jobs(inputs, action, "Speaking")
        return
    content = stdin.read() if source.text is None else source.text
    label = "stdin" if source.text is None else "text"
    with staged_text(content) as staged:
        run_jobs([staged], action, "Speaking", label=lambda _: label)


if __name__ == "__main__":
    speak_cmd()
