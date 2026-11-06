"""Generic orchestration: chain N ProgressStep[Path] stages, report their
progress, and land the final result at a computed destination path.

This is the task-agnostic remainder of transcribe_sidecar.py's
TranscriptionJob — the extractor/transcriber split there was specific to
transcribe (two steps); other tasks plug in their own step list instead
(text tasks use exactly one, TextStep).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Protocol, runtime_checkable

from glados.core.progress import BaseProgressReporter, ProgressEvent, ProgressStream

type DestinationFn = Callable[[Path], Path]

LOGGER = logging.getLogger(__name__)

# What running a Job on one input may raise because of that input or the
# tools it drives (missing/existing files, failed subprocesses, invalid
# content). Commands report these as clean errors; anything else is a bug.
JOB_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    subprocess.SubprocessError,
)


def temp_output_path(prefix: str, suffix: str) -> Path:
    """A new empty temp file for a step's output; the step owns it."""
    file_descriptor, path_str = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(file_descriptor)
    return Path(path_str)


@runtime_checkable
class ProgressStep[T](Protocol):
    def run(self, input_path: Path) -> ProgressStream[T]: ...


def suffix_destination(extension: str) -> DestinationFn:
    """input.ext -> input.<extension> — safe only when the output
    extension always differs from the input's (e.g. transcribe: video/
    audio -> srt/vtt/txt/...). Do NOT use this for same-extension tasks
    (rewrite/summarize/expand all take .txt -> .txt) — it would silently
    overwrite the source; use infix_destination for those instead.
    """

    def dest_fn(input_path: Path) -> Path:
        return input_path.with_suffix(f".{extension}")

    return dest_fn


def infix_destination(infix: str) -> DestinationFn:
    """input.txt -> input.<infix>.txt — for tasks whose output extension
    can match the input's."""

    def dest_fn(input_path: Path) -> Path:
        return input_path.with_name(f"{input_path.stem}.{infix}{input_path.suffix}")

    return dest_fn


def override_destination(
    explicit: Path | None, default_fn: DestinationFn
) -> DestinationFn:
    """Wrap a task's default destination policy so an explicit -o/--output
    path (if given) always wins, regardless of which default policy
    (suffix_destination/infix_destination) the task normally uses."""

    def dest_fn(input_path: Path) -> Path:
        return explicit if explicit is not None else default_fn(input_path)

    return dest_fn


def check_destination(dest: Path, overwrite: bool) -> None:
    """Refuse an existing destination unless overwriting was asked for."""
    if dest.exists() and not overwrite:
        raise FileExistsError(
            f"destination already exists, refusing to overwrite: {dest} (use -y/--overwrite)"
        )


def move_to_destination(produced: Path, dest: Path, overwrite: bool) -> None:
    """Move a finished temp file into place, re-checking the destination
    right before the move to avoid a race."""
    check_destination(dest, overwrite)
    LOGGER.debug("moving %s to %s", produced, dest)
    shutil.move(str(produced), str(dest))


type TextTransform = Callable[[str], ProgressStream[str]]


class TextStep:
    """Reads `input_path` as UTF-8 text, runs `transform` on it and writes
    the result to a temp file with the input's suffix. Satisfies
    ProgressStep[Path]; the single step of every text task."""

    def __init__(self, transform: TextTransform) -> None:
        self.transform = transform

    def run(self, input_path: Path) -> ProgressStream[Path]:
        events = self.transform(input_path.read_text(encoding="utf-8"))
        final_event: ProgressEvent[str] | None = None
        try:
            for event in events:
                if event.done:
                    final_event = event
                else:
                    yield event
        except BaseException:
            events.close()
            raise

        if final_event is None or not final_event.result:
            raise RuntimeError("backend ended without producing any text")

        output_path = temp_output_path("glados-text-", input_path.suffix)
        try:
            output_path.write_text(final_event.result, encoding="utf-8")
        except BaseException:
            output_path.unlink(missing_ok=True)
            raise

        yield replace(final_event, result=output_path)


type BytesTransform = Callable[[bytes], bytes]


class BytesStep:
    """Reads `input_path` as bytes, runs `transform` on it and writes the
    result to a temp file with `suffix` (default: the input's), carrying
    over the input's permissions and timestamps. The byte-level
    counterpart of TextStep, for quick in-memory transforms."""

    def __init__(self, transform: BytesTransform, suffix: str | None = None) -> None:
        self.transform = transform
        self.suffix = suffix

    def run(self, input_path: Path) -> ProgressStream[Path]:
        content = self.transform(input_path.read_bytes())
        output_path = temp_output_path(
            "glados-bytes-", self.suffix or input_path.suffix
        )
        try:
            output_path.write_bytes(content)
            shutil.copystat(input_path, output_path)
        except BaseException:
            output_path.unlink(missing_ok=True)
            raise
        yield ProgressEvent(completed=1, total=1, done=True, result=output_path)


class Job:
    """Drives a fixed sequence of (step, description) pairs, each
    consuming the previous step's output path, and moves the final
    result to `dest_fn(input_path)`. Overwrite/race-check behavior is
    unchanged from transcribe_sidecar.py's TranscriptionJob.
    """

    def __init__(
        self,
        steps: Sequence[tuple[ProgressStep[Path], str]],
        dest_fn: DestinationFn,
    ) -> None:
        self.steps = steps
        self.dest_fn = dest_fn

    @staticmethod
    def _consume[T](
        events: ProgressStream[T], reporter: BaseProgressReporter, description: str
    ) -> T:
        """Drive a ProgressEvent stream, reflecting it into the reporter,
        and return the result carried by the final event."""
        task_id = reporter.add_task(description, total=None)
        result: T | None = None
        for event in events:
            reporter.update(task_id, completed=event.completed, total=event.total)
            if event.done:
                reporter.complete(task_id)
                result = event.result
        if result is None:
            raise RuntimeError(f"{description}: step ended without producing a result")
        return result

    def run(
        self, input_path: Path, reporter: BaseProgressReporter, overwrite: bool = False
    ) -> Path:
        if not input_path.is_file():
            raise FileNotFoundError(f"input file not found: {input_path}")

        dest = self.dest_fn(input_path)
        check_destination(dest, overwrite)

        current = input_path
        intermediates: list[Path] = []
        moved = False
        try:
            for step, description in self.steps:
                current = self._consume(step.run(current), reporter, description)
                LOGGER.debug("%s: produced %s", description, current)
                intermediates.append(current)

            move_to_destination(current, dest, overwrite)
            moved = True
            return dest
        finally:
            # every step's output is a temp file except the one that got
            # moved to dest (if we got that far) — clean up the rest
            cleanup = intermediates[:-1] if moved else intermediates
            for produced in cleanup:
                produced.unlink(missing_ok=True)
