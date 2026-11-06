"""Unified `glados` entry point — one subcommand per task.

Each task's click.Command (glados.tasks.<task>.cli) is the same object
added here as a subcommand AND installed on its own as a standalone tool
(see pyproject.toml's [project.scripts]) — no separate wiring needed for
either mode.

Backends are selected and loaded per command by core/backends.py; nothing
is imported or configured when this module is imported.
"""

from __future__ import annotations

import rich_click as click

from glados.tasks import expand, rewrite, summarize, transcribe

TASK_COMMANDS = [transcribe.cli, rewrite.cli, summarize.cli, expand.cli]


@click.group()
def cli() -> None:
    """Apply model-backed tasks to files: transcribe, rewrite, summarize, expand, ..."""


for command in TASK_COMMANDS:
    cli.add_command(command)


if __name__ == "__main__":
    cli()
