"""The `oddjob` entry point: one group holding every command.

Task commands (`TASK_COMMANDS`) resolve a backend through `pass_session`;
file commands (`FILE_COMMANDS`) never touch config or backends. Commands
taking PATH... walk directories recursively, keep going when one input
fails and exit 1 if any did. Commands that change files take -n/--dry-run.

Nothing is imported or configured when this module is imported: backends
are selected and loaded per command by core/backends.py.
"""

from __future__ import annotations

import rich_click as click

from oddjob.commands.audio_grep import audio_grep_cmd
from oddjob.commands.captions import img_embed_description_cmd
from oddjob.commands.cleanup import cleanup_cmd
from oddjob.commands.conversions import jpgize_cmd, mp4ize_cmd
from oddjob.commands.dates import date_copy_cmd
from oddjob.commands.describe import describe_cmd
from oddjob.commands.expand import expand_cmd
from oddjob.commands.imgedit import img_reduce_cmd, img_trim_cmd
from oddjob.commands.imghash import img_check_cmd, img_duplicates_cmd, img_hash_cmd
from oddjob.commands.motionphotos import motionphotos_cmd
from oddjob.commands.renames import fix_extensions_cmd, rename_by_hash_cmd
from oddjob.commands.rewrite import rewrite_cmd
from oddjob.commands.sidecars import sidecars_cmd
from oddjob.commands.speak import speak_cmd
from oddjob.commands.summarize import summarize_cmd
from oddjob.commands.transcribe import transcribe_cmd
from oddjob.commands.translate import translate_cmd

TASK_COMMANDS: list[click.Command] = [
    transcribe_cmd,
    speak_cmd,
    rewrite_cmd,
    summarize_cmd,
    expand_cmd,
    translate_cmd,
    describe_cmd,
    audio_grep_cmd,
]

FILE_COMMANDS: list[click.Command] = [
    sidecars_cmd,
    motionphotos_cmd,
    jpgize_cmd,
    mp4ize_cmd,
    img_hash_cmd,
    img_duplicates_cmd,
    img_check_cmd,
    img_trim_cmd,
    img_reduce_cmd,
    img_embed_description_cmd,
    rename_by_hash_cmd,
    fix_extensions_cmd,
    date_copy_cmd,
    cleanup_cmd,
]

# `oddjob --help` sections, by what a command works on.
PANELS: dict[str, list[str]] = {
    "Text": ["rewrite", "summarize", "expand", "translate"],
    "Audio": ["transcribe", "speak", "audio-grep"],
    "Images": [
        "img-hash",
        "img-duplicates",
        "img-check",
        "img-trim",
        "img-reduce",
        "img-embed-description",
        "describe",
    ],
    "Formats": ["jpgize", "mp4ize"],
    "Media": ["motionphotos", "date-copy"],
    "Files": ["rename-by-hash", "fix-extensions", "cleanup", "sidecars"],
}


def add_panels[F](func: F) -> F:
    for name, commands in reversed(PANELS.items()):
        func = click.command_panel(name, commands=commands)(func)
    return func


@click.group()
@add_panels
def cli() -> None:
    """Apply model backends and file utilities to files: transcribe,
    rewrite, summarize, translate and describe; convert, hash, crop,
    caption, rename, date-copy and clean up."""


for command in TASK_COMMANDS + FILE_COMMANDS:
    cli.add_command(command)


if __name__ == "__main__":
    cli()
