"""`multitool hash-rename`: plan every rename first, then apply them."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.batch import run_batch
from filejobs.cli_options import (
    dry_run_option,
    finish_batch,
    overwrite_option,
    paths_argument,
)
from filejobs.inputs import accept_all, expand_inputs
from filejobs.progress import BaseProgressReporter
from multitool import renamers


@click.command("hash-rename")
@paths_argument
@click.option(
    "--algo",
    type=click.Choice(renamers.digest_algorithms()),
    default=renamers.DEFAULT_ALGORITHM,
    show_default=True,
)
@overwrite_option
@dry_run_option
def hash_rename_cmd(
    paths: tuple[Path, ...], algo: str, overwrite: bool, dry_run: bool
) -> None:
    """Rename each file in PATH... to <digest of its content>.<ext>."""
    planned: list[renamers.Rename] = []

    def plan(path: Path, _reporter: BaseProgressReporter) -> None:
        rename = renamers.plan_rename(path, renamers.file_digest(path, algo))
        if rename is not None:
            planned.append(rename)

    hashing = run_batch(expand_inputs(paths, accept_all), plan, description="Hashing")
    if dry_run:
        for rename in planned:
            click.echo(rename.describe())
        finish_batch(hashing)
        return

    def apply(rename: renamers.Rename, _reporter: BaseProgressReporter) -> None:
        renamers.apply_rename(rename, overwrite)

    renaming = run_batch(
        planned,
        apply,
        description="Renaming",
        label=lambda rename: str(rename.source),
    )
    finish_batch(hashing, renaming)
