"""Shared helpers for the backend tests: fake executables, a fake HTTP server
and the integration settings.

Unit tests never touch real services. Integration tests read their settings
from `tests/integration.env` (git-ignored; copy `integration.env.example`),
with `GLADOS_TEST_*` environment variables taking precedence, and skip
themselves when a required setting is empty.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import threading
import unittest
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Self

from dotenv import dotenv_values

from filejobs.progress import ProgressEvent, ProgressStream

INTEGRATION_ENV = Path(__file__).with_name("integration.env")
SETTING_PREFIX = "GLADOS_TEST_"


def integration_settings() -> dict[str, str]:
    """Non-empty GLADOS_TEST_* settings: integration.env, then the environment."""
    file_values = dotenv_values(INTEGRATION_ENV) if INTEGRATION_ENV.is_file() else {}
    merged = {**file_values, **os.environ}
    return {
        name: value
        for name, value in merged.items()
        if name.startswith(SETTING_PREFIX) and value
    }


def require_settings(*names: str) -> dict[str, str]:
    """All integration settings, or SkipTest naming the missing ones."""
    settings = integration_settings()
    missing = [name for name in names if name not in settings]
    if missing:
        raise unittest.SkipTest(f"set {', '.join(missing)} in {INTEGRATION_ENV}")
    return settings


class NullReporter:
    """A progress reporter that shows nothing, for running Jobs in tests."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def add_task(self, description: str, total: float | None) -> int:
        return 0

    def update(
        self, task_id: int, completed: float, total: float | None = None
    ) -> None:
        return None

    def complete(self, task_id: int) -> None:
        return None

    def remove(self, task_id: int) -> None:
        return None


def drain[T](stream: ProgressStream[T]) -> tuple[list[ProgressEvent[T]], T | None]:
    """Consume a progress stream; return its events and the final result."""
    events = list(stream)
    if not events or not events[-1].done:
        raise AssertionError(f"stream did not end with a done event: {events}")
    return events, events[-1].result


def write_executable(directory: Path, name: str, script: str) -> Path:
    """Write `script` (Python source) as an executable run by this interpreter.
    The script can record its argv next to itself via `Path(__file__)`."""
    path = directory / name
    path.write_text(f"#!{sys.executable}\n{script}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def recorded_argv(executable: Path) -> list[str]:
    """The argv a fake executable stored in `<executable>.argv`."""
    return json.loads(executable.with_suffix(".argv").read_text(encoding="utf-8"))


def closed_port_url() -> str:
    """A localhost URL nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CannedResponse:
    status: int
    content_type: str
    body: bytes


class FakeHTTPServer:
    """Answers every POST with one canned response and records the requests."""

    def __init__(self, response: CannedResponse) -> None:
        self.response = response
        self.requests: list[RecordedRequest] = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                fake.requests.append(
                    RecordedRequest(
                        path=self.path,
                        headers=dict(self.headers),
                        body=json.loads(self.rfile.read(length)),
                    )
                )
                self.send_response(fake.response.status)
                self.send_header("Content-Type", fake.response.content_type)
                self.send_header("Content-Length", str(len(fake.response.body)))
                self.end_headers()
                self.wfile.write(fake.response.body)

            def log_message(self, fmt: str, *args: Any) -> None:
                """Keep the test output clean."""

        return Handler

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()
