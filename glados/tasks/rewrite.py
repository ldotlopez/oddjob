"""Rewrite task — signatures and CLI shape only; no backend implements
Rewriter yet.

Mirrors tasks/transcribe.py's shape: a *Step adapter satisfying
ProgressStep[Path] (core.pipeline.Job plugs into it directly), backends
discovered via foundation.plugin.Register (core/backend_discovery.py), and a
single click.Command reused as both the `glados rewrite` subcommand and
the standalone `rewrite` tool. A single step — no extraction stage needed
for text input — landing at infix_destination("rewrite") so
file.txt -> file.rewrite.txt by default (overridable with -o/--output;
see core.pipeline.suffix_destination's docstring for why
suffix_destination isn't safe here).
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from glados.core.backend_discovery import backends_for
from glados.core.cli_common import (
    GladosContext,
    backend_option,
    common_file_options,
    model_option,
    pass_glados_context,
)
from glados.core.pipeline import Job, infix_destination, override_destination
from glados.core.progress import ProgressStream
from glados.tasks.protocols import Rewriter

DEFAULT_INFIX = "rewrite"


class RewriteStep:
    """Will read `input_path`'s text, drive a Rewriter backend, and write
    the result to a temp file — same shape as transcribe.TranscribeStep.
    Not implemented yet."""

    def __init__(self, backend: Rewriter, instructions: str | None) -> None:
        self.backend = backend
        self.instructions = instructions

    def run(self, input_path: Path) -> ProgressStream[Path]:
        raise NotImplementedError("RewriteStep is not implemented yet")
        yield  # pragma: no cover — keeps this a generator, matching ProgressStep's shape


# Discovered via foundation.plugin.Register — empty today since no backend
# implements Rewriter yet (see core/backend_discovery.py). Once one does,
# this dict populates automatically; no code here needs to change.
_DEFAULT_BACKENDS: dict[str, Rewriter] = backends_for(Rewriter)
DEFAULT_BACKEND: str | None = None


@click.command("rewrite")
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option(
    "-i",
    "--instructions",
    default=None,
    help="rewrite instructions, e.g. 'more formal tone'",
)
@model_option
@backend_option(_DEFAULT_BACKENDS, DEFAULT_BACKEND)
@common_file_options
@pass_glados_context
def cli(
    ctx: GladosContext,
    input_path: Path,
    instructions: str | None,
    model: Path | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Rewrite INPUT_PATH per --instructions. Not yet implemented."""
    if not _DEFAULT_BACKENDS:
        raise click.ClickException("rewrite task has no backend implemented yet")
    backend_instance = _DEFAULT_BACKENDS[backend]
    job = Job(
        steps=[(RewriteStep(backend_instance, instructions), "Rewriting")],
        dest_fn=override_destination(output, infix_destination(DEFAULT_INFIX)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
