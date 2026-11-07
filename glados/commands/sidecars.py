"""`glados sidecars`: list groups of files sharing a name."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from filejobs.cli_options import paths_argument
from filejobs.inputs import accept_all, expand_inputs
from glados.core.cli_common import logging_options
from glados.lib import sidecars


@click.group("sidecars")
def sidecars_cmd() -> None:
    """Scan and search for sidecar files."""


@sidecars_cmd.command("scan")
@paths_argument
@click.option(
    "-e",
    "--extension",
    "extensions",
    multiple=True,
    help="only groups having all these extensions (at least two)",
)
@click.option(
    "--cs", "case_sensitive", is_flag=True, help="match extensions case-sensitively"
)
@logging_options
def scan_cmd(
    paths: tuple[Path, ...], extensions: tuple[str, ...], case_sensitive: bool
) -> None:
    """List groups of files sharing a name in PATH..."""
    if len(extensions) == 1:
        raise click.UsageError("give at least two extensions")
    groups = sidecars.group_sidecars(expand_inputs(paths, accept_all))
    if extensions:
        groups = sidecars.with_extensions(groups, extensions, case_sensitive)
    for group in groups:
        click.echo(f"{group.base}")
        for file in group.files:
            click.echo(f"  {sidecars.extension_of(file, case_sensitive)}: {file}")


@sidecars_cmd.command("find")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@logging_options
def find_cmd(file: Path) -> None:
    """List the sidecar files of FILE."""
    group = sidecars.sidecars_of(file, file.parent.iterdir())
    if group is None:
        click.echo("no sidecar files found")
        return
    for member in group.files:
        click.echo(str(member))
