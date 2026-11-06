"""Ollama native-API backend (`/api/chat`): implements rewrite, summarize,
expand.

Global options (`[backends.ollama]` in the config, or `-m/--model`): `model`,
`base_url`, `options` (passed through as Ollama's model options, e.g.
`num_ctx`, `temperature`) and `timeout` in seconds.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

import pydantic
import requests

from glados.core.progress import ProgressEvent, ProgressStream
from glados.core.text_backend import text_plugin_triples

LOGGER = logging.getLogger(__name__)


class OllamaOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    model: str = "llama3.2"
    base_url: str = "http://localhost:11434"
    options: dict[str, Any] = {}
    timeout: float = 600


def _error_message(response: requests.Response) -> str:
    try:
        return response.json()["error"]
    except (ValueError, KeyError, TypeError):
        return response.text.strip() or response.reason


class OllamaTransport:
    """Streams one `/api/chat` reply (newline-delimited JSON) per call.
    Satisfies core.text_backend.ChatTransport."""

    def __init__(self, options: OllamaOptions) -> None:
        self.options = options

    def complete(self, system: str, user: str) -> ProgressStream[str]:
        base_url = self.options.base_url.rstrip("/")
        body: dict[str, Any] = {
            "model": self.options.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
        }
        if self.options.options:
            body["options"] = self.options.options
        chunks: list[str] = []
        received = 0
        url = f"{base_url}/api/chat"
        LOGGER.debug("POST %s (model %s)", url, self.options.model)
        try:
            with requests.post(
                url,
                json=body,
                stream=True,
                timeout=self.options.timeout,
            ) as response:
                if not response.ok:
                    raise RuntimeError(
                        f"ollama request failed ({response.status_code}):"
                        f" {_error_message(response)}"
                    )
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    event = json.loads(line)
                    if "error" in event:
                        raise RuntimeError(f"ollama error: {event['error']}")
                    content = (event.get("message") or {}).get("content")
                    if content:
                        chunks.append(content)
                        received += len(content)
                        yield ProgressEvent(completed=received, total=None)
                    if event.get("done"):
                        break
        except requests.ConnectionError as exc:
            raise RuntimeError(
                f"cannot reach ollama at {base_url} (is `ollama serve` running?)"
            ) from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"ollama request failed: {exc}") from exc

        yield ProgressEvent(
            completed=received, total=received, done=True, result="".join(chunks)
        )


def __glados_plugin__(
    backend: str, options: Mapping[str, Any]
) -> list[tuple[str, type, object]]:
    """Build the transport with its global options; one triple per text
    task (see core/text_backend.py). This module provides only the
    `ollama` backend, so `backend` is not consulted."""
    return text_plugin_triples(OllamaTransport(OllamaOptions.model_validate(options)))
