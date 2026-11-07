"""Speak task: where the text comes from, and the step that voices it.

The text is a list of files, a literal (`--text`), or stdin; `choose_source`
settles which from the command line, as a pure function so every rule is
testable without a terminal. SpeakStep drives a Speaker backend over one
text file. A literal or piped text is staged in a temporary file
(`staged_text`) so it runs through the same Job as a file. The command is
glados/commands/speak.py.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from filejobs.progress import ProgressStream
from glados.lib.protocols import Speaker

STDIN_ARGUMENT = Path("-")
AUDIO_EXTENSION = "wav"
PLAN_TEXT_LIMIT = 40


class SourceError(ValueError):
    """The command line does not say, or contradicts itself on, what to speak."""


@dataclass(frozen=True, slots=True)
class FileSource:
    paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class TextSource:
    """A literal text, or None for the text on stdin (read when it runs)."""

    text: str | None


def choose_source(
    paths: tuple[Path, ...],
    text: str | None,
    output: Path | None,
    *,
    stdin_is_terminal: bool,
) -> FileSource | TextSource:
    """The text source the arguments select. Files win over a pipe, which is
    then left unread. A text or stdin source has no file name to derive the
    destination from, so it needs `output`."""
    reads_stdin = STDIN_ARGUMENT in paths
    if reads_stdin and (len(paths) > 1 or text is not None):
        raise SourceError("'-' (stdin) must be used alone")
    if paths and text is not None:
        raise SourceError("give either PATH... or --text, not both")
    if paths and not reads_stdin:
        return FileSource(paths)

    source: TextSource
    if text is not None:
        if not text.strip():
            raise SourceError("--text is empty")
        source = TextSource(text)
    elif reads_stdin or not stdin_is_terminal:
        source = TextSource(None)
    else:
        raise SourceError("no input: give PATH..., --text, or pipe text into stdin")

    if output is None:
        raise SourceError("-o/--output is required with --text or stdin")
    return source


def describe_text(text: str) -> str:
    """The text on one line, quoted and cut, for the --dry-run plan."""
    line = " ".join(text.split())
    if len(line) > PLAN_TEXT_LIMIT:
        line = f"{line[:PLAN_TEXT_LIMIT].rstrip()}..."
    return f'"{line}"'


@contextmanager
def staged_text(text: str) -> Iterator[Path]:
    """`text` in a temporary file, removed on exit."""
    with tempfile.TemporaryDirectory(prefix="glados-speak-") as directory:
        staged = Path(directory) / "speech.txt"
        staged.write_text(text, encoding="utf-8")
        yield staged


class SpeakStep:
    """Reads a text file and has a Speaker voice it into a temporary WAV
    file. Satisfies ProgressStep[Path] — plugs into filejobs.pipeline.Job."""

    def __init__(self, backend: Speaker, speaker: int | None) -> None:
        self.backend = backend
        self.speaker = speaker

    def run(self, input_path: Path) -> ProgressStream[Path]:
        text = input_path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"no text to speak in {input_path}")
        return self.backend.speak(text, speaker=self.speaker)
