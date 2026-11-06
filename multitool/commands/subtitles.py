"""`multitool srt-grep`: search transcriptions; one line per matching cue."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.batch import run_batch
from filejobs.cli_options import finish_batch, paths_argument
from filejobs.inputs import expand_inputs
from filejobs.progress import BaseProgressReporter
from multitool import subtitles


@click.command("srt-grep")
@click.argument("pattern")
@paths_argument
def srt_grep_cmd(pattern: str, paths: tuple[Path, ...]) -> None:
    """Print the cues containing PATTERN (ignoring case) in the .srt files of
    PATH...; a media file means its NAME.srt sidecar. Exit 1 if nothing
    matched."""
    matches: list[tuple[Path, subtitles.Cue]] = []

    def search(srt: Path, _reporter: BaseProgressReporter) -> None:
        cues = subtitles.parse_srt(srt.read_text(encoding="utf-8"))
        matches.extend((srt, cue) for cue in subtitles.matching_cues(cues, pattern))

    # A media file and its own .srt name the same input.
    srts = dict.fromkeys(
        subtitles.subtitle_path(path) for path in expand_inputs(paths, subtitles.is_srt)
    )
    report = run_batch(list(srts), search, description="Searching")
    for srt, cue in matches:
        click.echo(f"{srt} @ {cue.start}: {cue.text}")
    finish_batch(report)
    if not matches:
        raise click.exceptions.Exit(1)
