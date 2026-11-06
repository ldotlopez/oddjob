"""Generic progress-reporting primitives shared by every task and backend.

Lifted from transcribe_sidecar.py: nothing here knows about ffmpeg,
whisper, or any particular task — it's the vocabulary that runners,
backends, and the pipeline all speak.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable

from foundation.clilib import RICH_STDERR_ENABLED, get_stderr_console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)


@dataclass(slots=True)
class ProgressEvent[T = None]:
    """One point in a runner's progress stream.

    `total` may be None (unknown/indeterminate). The final event of a
    successful run has `done=True` and carries the run's result (if any)
    in `result` — generators can't return values through a `for` loop, so
    the result rides along on the last event instead. Generic over the
    result type: backends and pipeline steps each specialize T to
    whatever they produce (list[TranscriptSegment], str, Path, ...).
    """

    completed: float
    total: float | None
    done: bool = False
    result: T | None = None


type ProgressStream[T = None] = Iterator[ProgressEvent[T]]


@runtime_checkable
class BaseProgressReporter(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def add_task(self, description: str, total: float | None) -> int:
        """total=None means indeterminate."""
        ...

    def update(
        self, task_id: int, completed: float, total: float | None = None
    ) -> None: ...

    def complete(self, task_id: int) -> None: ...


class RichProgressReporter:
    def __init__(self) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=get_stderr_console(),
            transient=False,
        )

    def __enter__(self) -> Self:
        self._progress.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._progress.__exit__(*exc_info)

    def add_task(self, description: str, total: float | None) -> int:
        return self._progress.add_task(description, total=total)

    def update(
        self, task_id: int, completed: float, total: float | None = None
    ) -> None:
        kwargs: dict[str, float] = {"completed": completed}
        if total is not None:
            kwargs["total"] = total
        self._progress.update(task_id, **kwargs)

    def complete(self, task_id: int) -> None:
        task = self._progress.tasks[task_id]
        self._progress.update(task_id, completed=task.total if task.total else 100)


class PlainProgressReporter:
    """No colors, no cursor control — just occasional plain-text percentage lines."""

    STEP = 10  # print at most every STEP percentage points

    def __init__(self) -> None:
        self._descriptions: dict[int, str] = {}
        self._totals: dict[int, float | None] = {}
        self._last_printed: dict[int, int] = {}
        self._next_id = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def add_task(self, description: str, total: float | None) -> int:
        task_id = self._next_id
        self._next_id += 1
        self._descriptions[task_id] = description
        self._totals[task_id] = total
        self._last_printed[task_id] = -1
        print(f"{description}: starting", file=sys.stderr)
        return task_id

    def update(
        self, task_id: int, completed: float, total: float | None = None
    ) -> None:
        if total is not None:
            self._totals[task_id] = total
        task_total = self._totals[task_id]
        if not task_total:
            return
        pct = int(min(100, (completed / task_total) * 100))
        last = self._last_printed[task_id]
        if pct >= last + self.STEP or pct == 100:
            print(f"{self._descriptions[task_id]}: {pct}%", file=sys.stderr)
            self._last_printed[task_id] = pct

    def complete(self, task_id: int) -> None:
        print(f"{self._descriptions[task_id]}: done", file=sys.stderr)


def create_reporter() -> BaseProgressReporter:
    """Rich bars when stderr is a rich-capable terminal (see
    foundation.clilib), else plain percentage lines."""
    return RichProgressReporter() if RICH_STDERR_ENABLED else PlainProgressReporter()
