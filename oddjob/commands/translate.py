"""Translate command: text file -> translated text file via a Translator backend.

A single filejobs.pipeline.TextStep driving the backend selected by
core/backends.py, with the system prompt rendered from `[prompts] translate`
in the config. Lands at infix_destination(<language>), so with `-l es`
file.txt -> file.es.txt (lib/translate.py names the infix).
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import (
    dry_run_option,
    paths_argument,
    run_same_format_jobs,
    same_format_options,
)
from filejobs.inputs import text_inputs_except_outputs
from filejobs.pipeline import TextStep
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
@same_format_options
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
    in_place: bool,
    keep_mtime: bool,
    dry_run: bool,
) -> None:
    """Translate each input in PATH... into --language."""
    language, infix = target

    def make_step() -> TextStep:
        prompt = session.config().prompts.render_translate(language)
        translator = session.backend("translate", Translator, backend, {"model": model})
        return TextStep(lambda text: translator.translate(text, prompt=prompt))

    run_same_format_jobs(
        paths,
        text_inputs_except_outputs(infix),
        infix,
        make_step,
        "Translating",
        output=output,
        overwrite=overwrite,
        in_place=in_place,
        keep_mtime=keep_mtime,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    translate_cmd()
