"""Rewrite task: text file -> rewritten text file via a Rewriter backend.

A single core.pipeline.TextStep driving the backend selected by
core/backends.py, with the system prompt rendered from `[prompts] rewrite`
in the config. The same click.Command is the `glados rewrite` subcommand and
the standalone `rewrite` tool. Lands at infix_destination("rewrite"), so
file.txt -> file.rewrite.txt by default (see suffix_destination's docstring
for why it isn't safe here).
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
from glados.core.pipeline import Job, TextStep, infix_destination, override_destination
from glados.tasks.protocols import Rewriter

DEFAULT_INFIX = "rewrite"


@click.command("rewrite")
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option(
    "-i",
    "--instructions",
    default=None,
    help="rewrite instructions, e.g. 'more formal tone'"
    " (default: improve clarity and correctness)",
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
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
) -> None:
    """Rewrite INPUT_PATH per --instructions."""
    prompt = ctx.config().prompts.render_rewrite(instructions)
    rewriter = ctx.backend("rewrite", Rewriter, backend, {"model": model})
    job = Job(
        steps=[
            (TextStep(lambda text: rewriter.rewrite(text, prompt=prompt)), "Rewriting")
        ],
        dest_fn=override_destination(output, infix_destination(DEFAULT_INFIX)),
    )
    ctx.run_job(job, input_path, overwrite)


if __name__ == "__main__":
    cli()
