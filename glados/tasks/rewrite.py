"""Rewrite task — signatures and CLI shape only; no backend implements
Rewriter yet.

Mirrors tasks/transcribe.py's shape: a *Step adapter satisfying
ProgressStep[Path] (core.pipeline.Job plugs into it directly), the
backend selected and loaded by core/backends.py, and a
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

from glados.core.cli_common import (
    GladosContext,
    backend_option,
    common_file_options,
    logging_options,
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


@click.command("rewrite")
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option(
    "-i",
    "--instructions",
    default=None,
    help="rewrite instructions, e.g. 'more formal tone'",
)
@model_option
@backend_option("rewrite")
@common_file_options
@logging_options
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
    backend_instance = ctx.backend("rewrite", Rewriter, backend, {"model": model})
    job = Job(
        steps=[(RewriteStep(backend_instance, instructions), "Rewriting")],
        dest_fn=override_destination(output, infix_destination(DEFAULT_INFIX)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
