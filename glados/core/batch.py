"""Run one action per input and keep going when an input fails.

A failure is logged and recorded, the remaining inputs still run, and the
caller decides the exit status from the returned report.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from glados.core.progress import create_reporter

LOGGER = logging.getLogger(__name__)

# What one input's action may raise without stopping the rest: I/O errors
# (including FileExistsError), failed external tools and invalid inputs.
INPUT_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    subprocess.SubprocessError,
)


@dataclass(frozen=True, slots=True)
class Failure:
    item: str
    reason: str


@dataclass(slots=True)
class BatchReport:
    succeeded: int = 0
    failures: list[Failure] = field(default_factory=list)


def run_batch[T](
    items: Sequence[T],
    action: Callable[[T], None],
    *,
    description: str,
    label: Callable[[T], str] = str,
) -> BatchReport:
    """Call `action` on every item under one progress bar."""
    report = BatchReport()
    with create_reporter() as reporter:
        task_id = reporter.add_task(description, total=len(items))
        for index, item in enumerate(items, start=1):
            try:
                action(item)
            except INPUT_ERRORS as exc:
                LOGGER.error("%s: %s", label(item), exc)
                report.failures.append(Failure(item=label(item), reason=str(exc)))
            else:
                report.succeeded += 1
            reporter.update(task_id, completed=index, total=len(items))
        reporter.complete(task_id)
    return report
