"""Local piper backend: implements speak with the `piper` CLI (piper-tts).

Options (`[backends.piper]`, or `-m/--model`): `model` (path to a voice
`.onnx`, its `.json` beside it) and `binary`. The text goes to piper on
stdin and the audio comes back as a WAV file. Voice and binary are checked
when speaking starts, not when the backend is built.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pydantic
from platformdirs import user_data_dir

from filejobs.pipeline import temp_output_path
from filejobs.progress import ProgressEvent, ProgressStream
from filejobs.runners import CliArgs
from oddjob.lib.protocols import Speaker

LOGGER = logging.getLogger(__name__)

DEFAULT_VOICE = Path(user_data_dir("piper", appauthor=False)) / "default-voice.onnx"


class PiperOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    model: Path = DEFAULT_VOICE
    binary: str = "piper"

    @pydantic.field_validator("model")
    @classmethod
    def _expand_user(cls, value: Path) -> Path:
        return value.expanduser()


class PiperBackend:
    """`piper --model VOICE --output_file WAV [--speaker N]`, text on stdin.
    Long options only: the CLI's short flags differ between releases. piper
    reports no progress, so the stream is indeterminate until it finishes."""

    def __init__(self, options: PiperOptions) -> None:
        self.options = options

    def speak(self, text: str, *, speaker: int | None) -> ProgressStream[Path]:
        binary = self.options.binary
        voice = self.options.model
        if shutil.which(binary) is None:
            raise FileNotFoundError(f"piper binary not found on PATH: {binary}")
        if not voice.is_file():
            raise FileNotFoundError(
                f"piper voice not found: {voice} (set [backends.piper] model"
                " in the config, or pass -m/--model)"
            )

        audio = temp_output_path("piper-", ".wav")
        args: CliArgs = ["--model", str(voice), "--output_file", str(audio)]
        if speaker is not None:
            args += ["--speaker", str(speaker)]
        cmd = [binary, *args]
        LOGGER.debug("running: %s", shlex.join(cmd))

        yield ProgressEvent(completed=0, total=None)
        try:
            finished = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if finished.returncode != 0:
                raise RuntimeError(f"{binary} failed: {finished.stderr.strip()}")
            if audio.stat().st_size == 0:
                raise RuntimeError(f"{binary} wrote no audio")
        except BaseException:
            audio.unlink(missing_ok=True)
            raise
        yield ProgressEvent(completed=1, total=1, done=True, result=audio)


type BackendFactory = Callable[[Mapping[str, Any]], Speaker]

_FACTORIES: dict[str, BackendFactory] = {
    "piper": lambda options: PiperBackend(PiperOptions.model_validate(options)),
}


def __oddjob_plugin__(
    backend: str, options: Mapping[str, Any]
) -> list[tuple[str, type, object]]:
    """Build `backend` with its global options; one triple per task it
    implements, named after the task (see core/backends.py)."""
    try:
        factory = _FACTORIES[backend]
    except KeyError:
        raise ValueError(
            f"module {__name__} provides no backend {backend!r}"
            f" (provides: {', '.join(sorted(_FACTORIES))})"
        ) from None
    return [("speak", Speaker, factory(options))]
