"""Generic subprocess runners: no knowledge of this project's tasks.

Drives ffmpeg with arbitrary arguments and turns its progress output into
a ProgressStream, for transcribe and the jpgize/mp4ize conversions alike.
"""

from __future__ import annotations

import logging
import re
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import IO

from filejobs.progress import ProgressEvent, ProgressStream

type CliArgs = list[str]

LOGGER = logging.getLogger(__name__)

_TIMESTAMP_RE = re.compile(r"^(\d+):(\d+):(\d+)\.(\d+)$")


def _parse_ffmpeg_timestamp(ts: str) -> float | None:
    match = _TIMESTAMP_RE.match(ts)
    if not match:
        return None
    hours, minutes, seconds, fraction = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + float(f"0.{fraction}")


def drain_stream(stream: IO[str], sink: list[str]) -> None:
    """Read a subprocess stream to completion in a background thread so it
    never blocks while the main thread reads the other stream."""
    sink.extend(stream)
    stream.close()


class FFMpegRunner:
    """Runs ffmpeg with arbitrary arguments, yielding ProgressEvent parsed
    from `-progress pipe:1` machine-readable output.

    Callers supply only their input/filter/output arguments — `-progress`,
    `-nostats`, `-loglevel` and the overwrite flag are added here. `result`
    on the final event is always None: this layer doesn't know what output
    paths the caller's args produced, only whether ffmpeg succeeded.
    """

    def __init__(
        self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"
    ) -> None:
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        for bin_name in (self.ffmpeg_bin, self.ffprobe_bin):
            if shutil.which(bin_name) is None:
                raise FileNotFoundError(f"{bin_name} not found on PATH")

    def probe_duration(self, input_path: Path) -> float | None:
        cmd = [
            self.ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, check=True
            ).stdout.strip()
            return float(out)
        except (subprocess.CalledProcessError, ValueError):
            return None  # caller falls back to an indeterminate progress display

    def run(
        self, args: CliArgs, duration: float | None = None, overwrite: bool = True
    ) -> ProgressStream:
        cmd = [
            self.ffmpeg_bin,
            "-y" if overwrite else "-n",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-nostats",
            *args,
        ]
        LOGGER.debug("running: %s", shlex.join(cmd))

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        stderr_lines: list[str] = []
        stderr_thread = threading.Thread(
            target=drain_stream, args=(proc.stderr, stderr_lines)
        )
        stderr_thread.start()

        completed = 0.0
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time="):
                    elapsed = _parse_ffmpeg_timestamp(line.split("=", 1)[1])
                    if elapsed is not None:
                        completed = elapsed
                        yield ProgressEvent(completed=completed, total=duration)
                elif line == "progress=end":
                    break
        except GeneratorExit:
            proc.terminate()
            raise
        finally:
            if proc.stdout:
                proc.stdout.close()
            proc.wait()
            stderr_thread.join()

        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {''.join(stderr_lines).strip()}")

        yield ProgressEvent(
            completed=duration if duration else completed, total=duration, done=True
        )
