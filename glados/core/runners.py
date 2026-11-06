"""Generic subprocess runners: no knowledge of this project's tasks.

Reusable as-is anywhere a caller wants ffmpeg or whisper-cli driven with
arbitrary arguments while getting a ProgressStream back. Unchanged from
transcribe_sidecar.py other than the import path for ProgressEvent.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
from pathlib import Path

from glados.core.progress import ProgressEvent, ProgressStream

type CliArgs = list[str]

_TIMESTAMP_RE = re.compile(r"^(\d+):(\d+):(\d+)\.(\d+)$")


def _parse_ffmpeg_timestamp(ts: str) -> float | None:
    match = _TIMESTAMP_RE.match(ts)
    if not match:
        return None
    hours, minutes, seconds, fraction = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + float(f"0.{fraction}")


def _drain(stream, sink: list[str]) -> None:
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

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        stderr_lines: list[str] = []
        stderr_thread = threading.Thread(
            target=_drain, args=(proc.stderr, stderr_lines)
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


class WhisperCliRunner:
    """Runs whisper-cli with arbitrary arguments, yielding ProgressEvent
    parsed from `--print-progress` output.

    `--print-progress` is added here; everything else about the invocation
    (model, language, output format/prefix, input file) is the caller's.
    """

    _PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")

    def __init__(self, whisper_bin: str = "whisper-cli") -> None:
        # Deliberately no shutil.which() check here — unlike FFMpegRunner,
        # this runner backs a Transcriber registered via
        # foundation.plugin.Register, whose entry point may run at process
        # import time regardless of whether transcribe is even used this
        # invocation (see backends/whisper_backend.py's register()).
        # Failing fast here would make the binary's absence surface as a
        # silently-swallowed PluginError in discovery instead of a clear
        # error when someone actually tries to transcribe — so the check
        # is deferred to run(), the same reasoning as the model-path check
        # in WhisperCliBackend.transcribe().
        self.whisper_bin = whisper_bin

    def run(self, args: CliArgs) -> ProgressStream:
        if shutil.which(self.whisper_bin) is None:
            raise FileNotFoundError(
                f"whisper binary not found on PATH: {self.whisper_bin}"
            )

        cmd = [self.whisper_bin, "--print-progress", *args]

        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        stderr_lines: list[str] = []
        completed = 0.0
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)
                match = self._PROGRESS_RE.search(line)
                if match:
                    completed = float(match.group(1))
                    yield ProgressEvent(completed=completed, total=100)
        except GeneratorExit:
            proc.terminate()
            raise
        finally:
            if proc.stderr:
                proc.stderr.close()
            proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"whisper-cli failed: {''.join(stderr_lines).strip()}")

        yield ProgressEvent(completed=100, total=100, done=True)
