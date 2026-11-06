"""OpenAI Chat Completions backend: implements rewrite, summarize, expand.

Works with any OpenAI-compatible server through `base_url`. Global options
(`[backends.openai]` in the config, or `-m/--model`): `model`, `base_url`,
`api_key` (defaults to $OPENAI_API_KEY) and `timeout` in seconds. The key is
checked when a request starts, not when the backend is built.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from typing import Any

import pydantic
import requests

from filejobs.progress import ProgressEvent, ProgressStream
from glados.tasks.text_backend import text_plugin_triples

LOGGER = logging.getLogger(__name__)


class OpenAIOptions(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    model: str = "gpt-4.1-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: pydantic.SecretStr | None = pydantic.Field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY") or None,
        validate_default=True,
    )
    timeout: float = 600


def _error_message(response: requests.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text.strip() or response.reason


class OpenAITransport:
    """Streams one chat completion (server-sent events) per call.
    Satisfies tasks.text_backend.ChatTransport."""

    def __init__(self, options: OpenAIOptions) -> None:
        self.options = options

    def complete(self, system: str, user: str) -> ProgressStream[str]:
        if self.options.api_key is None:
            raise ValueError(
                "no OpenAI API key: set OPENAI_API_KEY or [backends.openai] api_key"
            )
        url = f"{self.options.base_url.rstrip('/')}/chat/completions"
        body = {
            "model": self.options.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.options.api_key.get_secret_value()}"}
        chunks: list[str] = []
        received = 0
        LOGGER.debug("POST %s (model %s)", url, self.options.model)
        try:
            with requests.post(
                url,
                json=body,
                headers=headers,
                stream=True,
                timeout=self.options.timeout,
            ) as response:
                if not response.ok:
                    raise RuntimeError(
                        f"openai request failed ({response.status_code}):"
                        f" {_error_message(response)}"
                    )
                saw_event = False
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    saw_event = True
                    payload = line.removeprefix("data:").strip()
                    if payload == "[DONE]":
                        break
                    event = json.loads(payload)
                    if "error" in event:
                        raise RuntimeError(f"openai error: {event['error']['message']}")
                    choices = event.get("choices") or [{}]
                    content = (choices[0].get("delta") or {}).get("content")
                    if content:
                        chunks.append(content)
                        received += len(content)
                        yield ProgressEvent(completed=received, total=None)
                if not saw_event:
                    raise RuntimeError(
                        f"openai: {url} answered without a completion stream"
                        f" (content type {response.headers.get('Content-Type')!r});"
                        " check base_url, it usually ends in /v1"
                    )
        except requests.RequestException as exc:
            raise RuntimeError(f"openai request failed: {exc}") from exc

        yield ProgressEvent(
            completed=received, total=received, done=True, result="".join(chunks)
        )


def __glados_plugin__(
    backend: str, options: Mapping[str, Any]
) -> list[tuple[str, type, object]]:
    """Build the transport with its global options; one triple per text
    task (see tasks/text_backend.py). This module provides only the
    `openai` backend, so `backend` is not consulted."""
    return text_plugin_triples(OpenAITransport(OpenAIOptions.model_validate(options)))
