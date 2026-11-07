"""Translate command: text file -> translated text file via a Translator backend.

A single filejobs.pipeline.TextStep driving the backend selected by
core/backends.py, with the system prompt rendered from `[prompts] translate`
in the config. Lands at infix_destination(<language>), so with `-l es`
file.txt -> file.es.txt (tasks/translate.py names the infix). The same
click.Command is the `oddjob translate` subcommand and the standalone
`translate` tool.
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    check_single_output,
    common_file_options,
    dry_run_option,
    job_action,
    paths_argument,
    print_plan,
    run_jobs,
)
from filejobs.inputs import expand_inputs, text_inputs_except_outputs
from filejobs.pipeline import Job, TextStep, infix_destination, override_destination
from oddjob.core.cli_common import (
    backend_option,
    logging_options,
    model_option,
    pass_session,
)
from oddjob.core.session import Session
from oddjob.lib.protocols import Translator
from oddjob.lib.translate import language_infix


def infix_of(
    _ctx: click.Context, _param: click.Parameter, language: str
) -> tuple[str, str]:
    """-l value and its file name infix, rejected early if it has none."""
    try:
        return language, language_infix(language)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc


@click.command("translate")
@paths_argument
@click.option(
    "-l",
    "--language",
    "target",
    required=True,
    callback=infix_of,
    help="target language, e.g. 'es' or 'Brazilian Portuguese'"
    " (also names the output: FILE.<language>.<ext>)",
)
@model_option
@backend_option("translate")
@common_file_options
@dry_run_option
@logging_options
@pass_session
def translate_cmd(
    session: Session,
    paths: tuple[Path, ...],
    target: tuple[str, str],
    model: str | None,
    backend: str | None,
    output: Path | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Translate each input in PATH... into --language."""
    language, infix = target
    inputs = expand_inputs(paths, text_inputs_except_outputs(infix))
    check_single_output(output, inputs)
    dest_fn = override_destination(output, infix_destination(infix))
    if dry_run:
        print_plan(inputs, dest_fn)
        return
    prompt = session.config().prompts.render_translate(language)
    translator = session.backend("translate", Translator, backend, {"model": model})
    job = Job(
        steps=[
            (
                TextStep(lambda text: translator.translate(text, prompt=prompt)),
                "Translating",
            )
        ],
        dest_fn=dest_fn,
    )
    run_jobs(inputs, job_action(job, overwrite), "Translating")


if __name__ == "__main__":
    translate_cmd()
