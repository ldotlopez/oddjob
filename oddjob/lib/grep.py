"""Adapter for the system `grep`, used by oddjob/lib/audio_grep.py."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GrepResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class GrepRunner:
    """Runs grep with arbitrary arguments, capturing its output.
    FileNotFoundError if the binary is not on PATH."""

    def __init__(self, binary: str = "grep") -> None:
        if shutil.which(binary) is None:
            raise FileNotFoundError(f"{binary} not found on PATH")
        self.binary = binary

    def run(self, args: Sequence[str]) -> GrepResult:
        completed = subprocess.run(
            [self.binary, *args], capture_output=True, check=False
        )
        return GrepResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
