"""OpenAI backend: unit tests against a fake `/chat/completions`, and an
integration test against a real endpoint (GLADOS_TEST_OPENAI_* settings)."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest import mock

import pydantic
from support import (
    CannedResponse,
    FakeHTTPServer,
    closed_port_url,
    drain,
    require_settings,
)

from glados.plugins.openai import OpenAIOptions, OpenAITransport, __glados_plugin__
from glados.tasks.protocols import Expander, Rewriter, Summarizer, Translator

PING_SYSTEM = "Reply with exactly one word: pong. No punctuation."


def sse(*events: dict[str, Any], terminate: bool = True) -> CannedResponse:
    lines = [f"data: {json.dumps(event)}\n\n" for event in events]
    if terminate:
        lines.append("data: [DONE]\n\n")
    return CannedResponse(200, "text/event-stream", "".join(lines).encode("utf-8"))


def delta(content: str | None) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {"content": content}}]}


class OpenAITransportTest(unittest.TestCase):
    def serve(self, response: CannedResponse) -> FakeHTTPServer:
        return self.enterContext(FakeHTTPServer(response))

    def transport(self, base_url: str, **options: Any) -> OpenAITransport:
        options.setdefault("api_key", "sk-test")
        return OpenAITransport(OpenAIOptions(base_url=base_url, **options))

    def test_streams_reply(self) -> None:
        server = self.serve(
            sse(delta("Hola, "), delta(None), delta("mundo"), {"choices": []})
        )

        events, result = drain(
            self.transport(server.base_url + "/v1").complete("s", "u")
        )

        self.assertEqual(result, "Hola, mundo")
        self.assertEqual([event.completed for event in events], [6, 11, 11])
        self.assertEqual(events[-1].total, 11)

    def test_request(self) -> None:
        server = self.serve(sse(delta("ok")))
        transport = self.transport(server.base_url + "/v1/", model="gpt-x")

        drain(transport.complete("system prompt", "user text"))

        [request] = server.requests
        self.assertEqual(request.path, "/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")
        self.assertEqual(
            request.body,
            {
                "model": "gpt-x",
                "messages": [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "user text"},
                ],
                "stream": True,
            },
        )

    def test_stops_at_done_marker(self) -> None:
        body = sse(delta("a")).body + b"data: " + json.dumps(delta("ignored")).encode()
        server = self.serve(CannedResponse(200, "text/event-stream", body + b"\n\n"))

        _, result = drain(self.transport(server.base_url).complete("s", "u"))

        self.assertEqual(result, "a")

    def test_http_error_reports_message(self) -> None:
        body = json.dumps({"error": {"message": "Incorrect API key"}}).encode("utf-8")
        server = self.serve(CannedResponse(401, "application/json", body))

        with self.assertRaisesRegex(RuntimeError, r"\(401\): Incorrect API key"):
            drain(self.transport(server.base_url).complete("s", "u"))

    def test_response_without_stream_is_an_error(self) -> None:
        page = b"<!doctype html><title>Open WebUI</title>"
        server = self.serve(CannedResponse(200, "text/html", page))

        with self.assertRaisesRegex(RuntimeError, "without a completion stream"):
            drain(self.transport(server.base_url).complete("s", "u"))

    def test_empty_stream_is_not_an_error(self) -> None:
        server = self.serve(sse())

        _, result = drain(self.transport(server.base_url).complete("s", "u"))

        self.assertEqual(result, "")

    def test_stream_error_event(self) -> None:
        server = self.serve(sse(delta("partial"), {"error": {"message": "overloaded"}}))

        with self.assertRaisesRegex(RuntimeError, "openai error: overloaded"):
            drain(self.transport(server.base_url).complete("s", "u"))

    def test_unreachable_server(self) -> None:
        transport = self.transport(closed_port_url(), timeout=5)

        with self.assertRaisesRegex(RuntimeError, "openai request failed"):
            drain(transport.complete("s", "u"))

    def test_missing_api_key(self) -> None:
        transport = OpenAITransport(OpenAIOptions(api_key=None))

        with self.assertRaisesRegex(ValueError, "no OpenAI API key"):
            drain(transport.complete("s", "u"))


class OpenAIPluginTest(unittest.TestCase):
    def test_implements_text_tasks(self) -> None:
        triples = __glados_plugin__("openai", {"api_key": "sk-test"})

        self.assertEqual(
            [(task, protocol) for task, protocol, _ in triples],
            [
                ("rewrite", Rewriter),
                ("summarize", Summarizer),
                ("expand", Expander),
                ("translate", Translator),
            ],
        )
        for _, protocol, backend in triples:
            self.assertIsInstance(backend, protocol)

    def test_api_key_defaults_to_environment(self) -> None:
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-from-env"}):
            options = OpenAIOptions()

        self.assertIsNotNone(options.api_key)
        self.assertEqual(options.api_key.get_secret_value(), "sk-from-env")

    def test_api_key_hidden_in_repr(self) -> None:
        self.assertNotIn("sk-secret", repr(OpenAIOptions(api_key="sk-secret")))

    def test_rejects_unknown_options(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            __glados_plugin__("openai", {"organization": "org-1"})


class OpenAIIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = require_settings("GLADOS_TEST_OPENAI_API_KEY")

    def test_completes(self) -> None:
        defaults = OpenAIOptions(api_key=None)
        options = OpenAIOptions(
            api_key=self.settings["GLADOS_TEST_OPENAI_API_KEY"],
            model=self.settings.get("GLADOS_TEST_OPENAI_MODEL", defaults.model),
            base_url=self.settings.get(
                "GLADOS_TEST_OPENAI_BASE_URL", defaults.base_url
            ),
            timeout=120,
        )

        _, result = drain(OpenAITransport(options).complete(PING_SYSTEM, "ping"))

        self.assertIn("pong", (result or "").lower())


if __name__ == "__main__":
    unittest.main()
