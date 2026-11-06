"""The text tasks (rewrite, summarize, expand) on top of a chat transport.

Each LLM backend in glados/plugins only knows how to send one system prompt
plus one user message and stream the reply (ChatTransport). TextBackend turns
any such transport into an object satisfying Rewriter, Summarizer and
Expander, so the prompts stay task-owned (core.config.Prompts) and the
backends stay plain transports.
"""

from __future__ import annotations

from typing import Protocol

from glados.core.progress import ProgressStream
from glados.tasks.protocols import Expander, Rewriter, Summarizer


class ChatTransport(Protocol):
    def complete(self, system: str, user: str) -> ProgressStream[str]:
        """Send `system` as the system prompt and `user` as the user
        message. Yield ProgressEvent(completed=<characters so far>,
        total=None) while the reply streams, then a final done=True event
        carrying the whole reply as `result`."""
        ...


class TextBackend:
    """Satisfies Rewriter, Summarizer and Expander with one transport."""

    def __init__(self, transport: ChatTransport) -> None:
        self.transport = transport

    def rewrite(self, text: str, *, prompt: str) -> ProgressStream[str]:
        return self.transport.complete(prompt, text)

    def summarize(self, text: str, *, prompt: str) -> ProgressStream[str]:
        return self.transport.complete(prompt, text)

    def expand(self, text: str, *, prompt: str) -> ProgressStream[str]:
        return self.transport.complete(prompt, text)


def text_plugin_triples(transport: ChatTransport) -> list[tuple[str, type, object]]:
    """The `__glados_plugin__` result for a backend implementing every text
    task through `transport` (see core/backends.py)."""
    backend = TextBackend(transport)
    return [
        ("rewrite", Rewriter, backend),
        ("summarize", Summarizer, backend),
        ("expand", Expander, backend),
    ]
