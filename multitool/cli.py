"""`multitool` entry point: file utilities without the backend registry.

One command module per tool lives in multitool/commands/, sharing the
backend-free core in filejobs/; see docs/decisions/0003, 0005 and 0006.
Commands taking PATH... walk directories recursively,
keep going when one input fails and exit 1 if any did. Commands that change
files take -n/--dry-run.
"""

from __future__ import annotations

import rich_click as click

from filejobs.cli_options import logging_options_for
from multitool.commands.captions import img_caption_cmd
from multitool.commands.cleanup import fs_cleanup_cmd
from multitool.commands.conversions import jpgize_cmd, mp4ize_cmd
from multitool.commands.imgedit import autocrop_cmd, img_reduce_cmd
from multitool.commands.imghash import (
    img_check_cmd,
    img_duplicates_cmd,
    img_hash_cmd,
)
from multitool.commands.motionphotos import motionphotos_cmd
from multitool.commands.renames import fix_extensions_cmd, hash_rename_cmd
from multitool.commands.sidecars import sidecars_cmd
from multitool.commands.subtitles import srt_grep_cmd

APP_LOGGER = "multitool"

COMMANDS = [
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
    fs_cleanup_cmd,
    srt_grep_cmd,
]


@click.group()
@logging_options_for(APP_LOGGER)
def cli() -> None:
    """File utilities: sidecars, motion photos, conversions, image hashes,
    renames."""


for command in COMMANDS:
    cli.add_command(command)


if __name__ == "__main__":
    cli()
