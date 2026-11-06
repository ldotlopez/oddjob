"""srt-grep: search SubRip (.srt) transcriptions, such as the ones
`glados transcribe -f srt` writes next to each media file."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SRT_EXTENSION = ".srt"
_TIMING = re.compile(r"^(\d{2}:\d{2}:\d{2},\d{3}) --> \d{2}:\d{2}:\d{2},\d{3}")


@dataclass(frozen=True, slots=True)
class Cue:
    start: str  # as written in the file: HH:MM:SS,mmm
    text: str  # the cue's lines joined with spaces


def is_srt(path: Path) -> bool:
    return path.suffix.lower() == SRT_EXTENSION


def subtitle_path(path: Path) -> Path:
    """`path` itself if it is an .srt file, else its NAME.srt sidecar."""
    return path if is_srt(path) else path.with_suffix(SRT_EXTENSION)


def parse_srt(content: str) -> list[Cue]:
    """The cues of an .srt file. ValueError on a block with no timing line."""
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", content.lstrip("﻿").replace("\r\n", "\n"))
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue
        timing_index = 1 if lines[0].strip().isdigit() else 0
        if len(lines) <= timing_index:
            raise ValueError(f"cue without timing: {block.strip()!r}")
        timing = _TIMING.match(lines[timing_index].strip())
        if timing is None:
            raise ValueError(f"not an srt timing line: {lines[timing_index]!r}")
        text = " ".join(line.strip() for line in lines[timing_index + 1 :])
        cues.append(Cue(start=timing.group(1), text=text))
    return cues


def matching_cues(cues: list[Cue], pattern: str) -> list[Cue]:
    """Cues whose text contains `pattern`, ignoring case."""
    needle = pattern.casefold()
    return [cue for cue in cues if needle in cue.text.casefold()]
