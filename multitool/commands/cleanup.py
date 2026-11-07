"""`multitool fs-cleanup`: plan every removal (and chmod) first, then apply."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.batch import run_batch
from filejobs.cli_options import dry_run_option, finish_batch, paths_argument
from filejobs.progress import BaseProgressReporter
from glados.lib import cleanup


@click.command("fs-cleanup")
@paths_argument
@click.option(
    "--perms",
    "fix_permissions",
    is_flag=True,
    help="also chmod files to 644 and directories to 755",
)
@dry_run_option
def fs_cleanup_cmd(
    paths: tuple[Path, ...], fix_permissions: bool, dry_run: bool
) -> None:
    """Remove OS leftovers in PATH...: macOS (.DS_Store, ._NAME next to NAME,
    Icon\\r, .Spotlight-V100, .Trashes, .fseventsd, .TemporaryItems,
    .AppleDouble), Windows (Thumbs.db, ehthumbs.db, desktop.ini, $RECYCLE.BIN),
    KDE (.directory) and .Trash-<uid>."""
    planned = cleanup.plan_cleanup(paths, fix_permissions)
    if dry_run:
        for action in planned:
            click.echo(action.describe())
        return
    if not planned:  # a clean tree is the expected case, not a warning
        return

    def apply(action: cleanup.CleanupAction, _reporter: BaseProgressReporter) -> None:
        action.apply()

    report = run_batch(
        planned, apply, description="Cleaning", label=lambda action: str(action.path)
    )
    finish_batch(report)
