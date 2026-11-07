"""The `glados` entry point: one group holding every command.

Task commands (`TASK_COMMANDS`) resolve a backend through `pass_glados`;
file commands (`FILE_COMMANDS`) never touch config or backends. Commands
taking PATH... walk directories recursively, keep going when one input
fails and exit 1 if any did. Commands that change files take -n/--dry-run.

Nothing is imported or configured when this module is imported: backends
are selected and loaded per command by core/backends.py.
"""

from __future__ import annotations

import rich_click as click

from glados.commands.audio_grep import audio_grep_cmd
from glados.commands.captions import img_caption_cmd
from glados.commands.cleanup import fs_cleanup_cmd
from glados.commands.conversions import jpgize_cmd, mp4ize_cmd
from glados.commands.dates import date_sync_cmd
from glados.commands.describe import describe_cmd
from glados.commands.expand import expand_cmd
from glados.commands.imgedit import autocrop_cmd, img_reduce_cmd
from glados.commands.imghash import img_check_cmd, img_duplicates_cmd, img_hash_cmd
from glados.commands.motionphotos import motionphotos_cmd
from glados.commands.renames import fix_extensions_cmd, hash_rename_cmd
from glados.commands.rewrite import rewrite_cmd
from glados.commands.sidecars import sidecars_cmd
from glados.commands.summarize import summarize_cmd
from glados.commands.transcribe import transcribe_cmd
from glados.commands.translate import translate_cmd

TASK_COMMANDS: list[click.Command] = [
    transcribe_cmd,
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
    autocrop_cmd,
    img_reduce_cmd,
    img_caption_cmd,
    hash_rename_cmd,
    fix_extensions_cmd,
    date_sync_cmd,
    fs_cleanup_cmd,
]

# `glados --help` sections, by what a command works on.
PANELS: dict[str, list[str]] = {
    "Text": ["rewrite", "summarize", "expand", "translate", "describe"],
    "Audio": ["transcribe", "audio-grep"],
    "Images": [
        "img-hash",
        "img-duplicates",
        "img-check",
        "autocrop",
        "img-reduce",
        "img-caption",
        "jpgize",
    ],
    "Media": ["mp4ize", "motionphotos", "sidecars", "date-sync"],
    "Files": ["hash-rename", "fix-extensions", "fs-cleanup"],
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
    caption, rename, date-sync and clean up."""


for command in TASK_COMMANDS + FILE_COMMANDS:
    cli.add_command(command)


if __name__ == "__main__":
    cli()
