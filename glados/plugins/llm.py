"""`llm` CLI backend (https://llm.datasette.io): implements the text tasks
(rewrite, summarize, expand, translate, describe) by running `llm prompt`
as a subprocess.

Global options (`[backends.llm]` in the config, or `-m/--model`): `model`
(any model `llm models` lists; unset means llm's own default model) and
`binary` (the llm executable). Keys, plugins and logging are llm's own
configuration. The binary is checked when a request starts.
"""

from __future__ import annotations

import codecs
import io
import logging
import shlex
import shutil
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pydantic

from filejobs.progress import ProgressEvent, ProgressStream
from filejobs.runners import CliArgs, drain_stream
from glados.tasks.text_backend import text_plugin_triples

LOGGER = logging.getLogger(__name__)

READ_SIZE = 4096


class LlmOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    model: str | None = None
    binary: str = "llm"


class LlmCliTransport:
    """Runs `llm prompt -s <system>` with the user text on stdin (no argv
    length limit) and each image as `-a PATH`, and streams its stdout. Satisfies
    tasks.text_backend.ChatTransport."""

    def __init__(self, options: LlmOptions) -> None:
        self.options = options

    def complete(
        self, system: str, user: str, images: Sequence[Path] = ()
    ) -> ProgressStream[str]:
        if shutil.which(self.options.binary) is None:
            raise FileNotFoundError(
                f"llm binary not found on PATH: {self.options.binary}"
            )

        cmd: CliArgs = [self.options.binary, "prompt", "-s", system]
        if self.options.model:
            cmd += ["-m", self.options.model]
        for image in images:
            cmd += ["-a", str(image)]

        LOGGER.debug("running: %s", shlex.join(cmd))
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert proc.stdin is not None and proc.stdout is not None
        assert proc.stderr is not None
        stderr_lines: list[str] = []
        stderr_thread = threading.Thread(
            target=drain_stream,
            args=(
                io.TextIOWrapper(proc.stderr, encoding="utf-8", errors="replace"),
                stderr_lines,
            ),
        )
        stderr_thread.start()

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        chunks: list[str] = []
        received = 0
        try:
            try:
                proc.stdin.write(user.encode("utf-8"))
                proc.stdin.close()
            except BrokenPipeError:
                pass  # llm exited early; its stderr and exit code explain why
            while block := proc.stdout.read1(READ_SIZE):
                content = decoder.decode(block)
                if content:
                    chunks.append(content)
                    received += len(content)
                    yield ProgressEvent(completed=received, total=None)
            chunks.append(decoder.decode(b"", final=True))
        except GeneratorExit:
            proc.terminate()
            raise
        finally:
            proc.stdout.close()
            proc.wait()
            stderr_thread.join()

        if proc.returncode != 0:
            raise RuntimeError(f"llm failed: {''.join(stderr_lines).strip()}")

        yield ProgressEvent(
            completed=received, total=received, done=True, result="".join(chunks)
        )


def __glados_plugin__(
    backend: str, options: Mapping[str, Any]
) -> list[tuple[str, type, object]]:
    """Build the transport with its global options; one triple per text
    task (see tasks/text_backend.py). This module provides only the
    `llm` backend, so `backend` is not consulted."""
    return text_plugin_triples(LlmCliTransport(LlmOptions.model_validate(options)))
