"""Ollama backend: unit tests against a fake `/api/chat`, and an integration
test against a real server (GLADOS_TEST_OLLAMA_* settings)."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pydantic
from support import (
    CannedResponse,
    FakeHTTPServer,
    closed_port_url,
    drain,
    require_settings,
)

from glados.lib.protocols import (
    Describer,
    Expander,
    Rewriter,
    Summarizer,
    Translator,
)
from glados.plugins.ollama import OllamaOptions, OllamaTransport, __glados_plugin__

PING_SYSTEM = "Reply with exactly one word: pong. No punctuation."


def ndjson(*events: dict[str, Any]) -> CannedResponse:
    body = b"".join(json.dumps(event).encode("utf-8") + b"\n" for event in events)
    return CannedResponse(200, "application/x-ndjson", body)


def chunk(content: str, *, done: bool = False) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": content}, "done": done}


class OllamaTransportTest(unittest.TestCase):
    def serve(self, response: CannedResponse) -> FakeHTTPServer:
        return self.enterContext(FakeHTTPServer(response))

    def transport(self, server_url: str, **options: Any) -> OllamaTransport:
        return OllamaTransport(OllamaOptions(base_url=server_url, **options))

    def test_streams_reply(self) -> None:
        server = self.serve(
            ndjson(chunk("Hola, "), chunk("mundo"), chunk("", done=True))
        )

        events, result = drain(self.transport(server.base_url).complete("s", "u"))

        self.assertEqual(result, "Hola, mundo")
        self.assertEqual([event.completed for event in events], [6, 11, 11])
        self.assertEqual(events[-1].total, 11)

    def test_request_body(self) -> None:
        server = self.serve(ndjson(chunk("ok", done=True)))
        transport = self.transport(
            server.base_url + "/", model="qwen3", options={"num_ctx": 8192}
        )

        drain(transport.complete("system prompt", "user text"))

        [request] = server.requests
        self.assertEqual(request.path, "/api/chat")
        self.assertEqual(
            request.body,
            {
                "model": "qwen3",
                "messages": [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "user text"},
                ],
                "stream": True,
                "options": {"num_ctx": 8192},
            },
        )

    def test_images_go_base64_in_the_user_message(self) -> None:
        server = self.serve(ndjson(chunk("ok", done=True)))
        image = Path(self.enterContext(tempfile.TemporaryDirectory())) / "a.jpg"
        image.write_bytes(b"jpeg bytes")

        drain(self.transport(server.base_url).complete("s", "", [image]))

        [request] = server.requests
        self.assertEqual(
            request.body["messages"][1],
            {
                "role": "user",
                "content": "",
                "images": [base64.b64encode(b"jpeg bytes").decode("ascii")],
            },
        )

    def test_sends_bearer_token(self) -> None:
        server = self.serve(ndjson(chunk("ok", done=True)))

        drain(self.transport(server.base_url, api_key="ol-secret").complete("s", "u"))

        self.assertEqual(
            server.requests[0].headers["Authorization"], "Bearer ol-secret"
        )

    def test_no_authorization_without_api_key(self) -> None:
        server = self.serve(ndjson(chunk("ok", done=True)))

        drain(self.transport(server.base_url).complete("s", "u"))

        self.assertNotIn("Authorization", server.requests[0].headers)

    def test_omits_empty_model_options(self) -> None:
        server = self.serve(ndjson(chunk("ok", done=True)))

        drain(self.transport(server.base_url).complete("s", "u"))

        self.assertNotIn("options", server.requests[0].body)

    def test_stops_at_done(self) -> None:
        server = self.serve(ndjson(chunk("a", done=True), chunk("ignored")))

        _, result = drain(self.transport(server.base_url).complete("s", "u"))

        self.assertEqual(result, "a")

    def test_http_error_reports_message(self) -> None:
        body = json.dumps({"error": "model 'qwen3' not found"}).encode("utf-8")
        server = self.serve(CannedResponse(404, "application/json", body))

        with self.assertRaisesRegex(RuntimeError, r"\(404\): model 'qwen3' not found"):
            drain(self.transport(server.base_url).complete("s", "u"))

    def test_stream_error_event(self) -> None:
        server = self.serve(ndjson(chunk("partial"), {"error": "out of memory"}))

        with self.assertRaisesRegex(RuntimeError, "ollama error: out of memory"):
            drain(self.transport(server.base_url).complete("s", "u"))

    def test_unreachable_server(self) -> None:
        transport = self.transport(closed_port_url(), timeout=5)

        with self.assertRaisesRegex(RuntimeError, "cannot reach ollama"):
            drain(transport.complete("s", "u"))


class OllamaPluginTest(unittest.TestCase):
    def test_implements_text_tasks(self) -> None:
        triples = __glados_plugin__("ollama", {})

        self.assertEqual(
            [(task, protocol) for task, protocol, _ in triples],
            [
                ("rewrite", Rewriter),
                ("summarize", Summarizer),
                ("expand", Expander),
                ("translate", Translator),
                ("describe", Describer),
            ],
        )
        for _, protocol, backend in triples:
            self.assertIsInstance(backend, protocol)

    def test_rejects_unknown_options(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            __glados_plugin__("ollama", {"num_ctx": 8192})

    def test_api_key_hidden_in_repr(self) -> None:
        self.assertNotIn("ol-secret", repr(OllamaOptions(api_key="ol-secret")))


class OllamaIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = require_settings("GLADOS_TEST_OLLAMA_MODEL")

    def test_completes(self) -> None:
        options = OllamaOptions(
            model=self.settings["GLADOS_TEST_OLLAMA_MODEL"],
            base_url=self.settings.get(
                "GLADOS_TEST_OLLAMA_BASE_URL", OllamaOptions().base_url
            ),
            options={"temperature": 0},
            api_key=self.settings.get("GLADOS_TEST_OLLAMA_API_KEY"),
        )

        _, result = drain(OllamaTransport(options).complete(PING_SYSTEM, "ping"))

        self.assertIn("pong", (result or "").lower())


if __name__ == "__main__":
    unittest.main()
