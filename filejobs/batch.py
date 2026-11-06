"""Run one action per input and keep going when an input fails.

A failure is logged when it happens and recorded; the remaining inputs still
run, and the caller decides the exit status from the returned report. Each
action gets a reporter for its own steps (typically one Job run), whose bars
disappear once done so only the batch's overall bar stays.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Self

from filejobs.pipeline import JOB_ERRORS
from filejobs.progress import BaseProgressReporter, create_reporter

LOGGER = logging.getLogger(__name__)

type BatchAction[T] = Callable[[T, BaseProgressReporter], None]


@dataclass(frozen=True, slots=True)
class Failure:
    item: str
    reason: str


@dataclass(slots=True)
class BatchReport:
    succeeded: int = 0
    failures: list[Failure] = field(default_factory=list)


class TransientStepReporter:
    """Delegates to the batch's reporter, removing each task once complete."""

    def __init__(self, reporter: BaseProgressReporter) -> None:
        self.reporter = reporter

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def add_task(self, description: str, total: float | None) -> int:
        return self.reporter.add_task(description, total)

    def update(
        self, task_id: int, completed: float, total: float | None = None
    ) -> None:
        self.reporter.update(task_id, completed, total)

    def complete(self, task_id: int) -> None:
        self.reporter.complete(task_id)
        self.reporter.remove(task_id)

    def remove(self, task_id: int) -> None:
        self.reporter.remove(task_id)


def run_batch[T](
    items: Sequence[T],
    action: BatchAction[T],
    *,
    description: str,
    label: Callable[[T], str] = str,
) -> BatchReport:
    """Call `action` on every item under one progress bar."""
    report = BatchReport()
    if not items:
        LOGGER.warning("%s: no input files", description)
        return report
    with create_reporter() as reporter:
        steps = TransientStepReporter(reporter)
        task_id = reporter.add_task(description, total=len(items))
        for index, item in enumerate(items, start=1):
            try:
                action(item, steps)
            except JOB_ERRORS as exc:
                LOGGER.error("%s: %s", label(item), exc)
                report.failures.append(Failure(item=label(item), reason=str(exc)))
            else:
                report.succeeded += 1
            reporter.update(task_id, completed=index, total=len(items))
        reporter.complete(task_id)
    return report
