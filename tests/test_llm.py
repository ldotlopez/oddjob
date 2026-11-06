"""`llm` CLI backend: unit tests against a fake `llm`, and an integration
test against the real one (GLADOS_TEST_LLM_* settings)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pydantic
from support import drain, recorded_argv, require_settings, write_executable

from glados.plugins.llm import LlmCliTransport, LlmOptions, __glados_plugin__
from glados.tasks.protocols import Expander, Rewriter, Summarizer

ECHO_LLM = """
import json
import sys
from pathlib import Path

Path(__file__).with_suffix(".argv").write_text(json.dumps(sys.argv[1:]))
system = sys.argv[sys.argv.index("-s") + 1]
user = sys.stdin.buffer.read().decode("utf-8")
sys.stdout.buffer.write(f"{system}|{user}".encode("utf-8"))
"""

FAILING_LLM = """
import sys

print("Error: Unknown model: nonexistent", file=sys.stderr)
sys.exit(1)
"""

PING_SYSTEM = "Reply with exactly one word: pong. No punctuation."


class LlmTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def transport(
        self, script: str, model: str | None = None
    ) -> tuple[LlmCliTransport, Path]:
        binary = write_executable(self.workdir, "llm", script)
        return LlmCliTransport(LlmOptions(model=model, binary=str(binary))), binary

    def test_streams_reply(self) -> None:
        transport, _ = self.transport(ECHO_LLM)

        events, result = drain(transport.complete("be brief", "hello"))

        self.assertEqual(result, "be brief|hello")
        self.assertEqual(events[-1].completed, len(result))
        self.assertEqual(events[-1].total, len(result))
        self.assertTrue(all(event.total is None for event in events[:-1]))

    def test_multibyte_text_split_across_reads(self) -> None:
        transport, _ = self.transport(ECHO_LLM)
        user = "ñ€😀" * 5000  # well over one 4096-byte read

        _, result = drain(transport.complete("s", user))

        self.assertEqual(result, f"s|{user}")

    def test_invocation_with_model(self) -> None:
        transport, binary = self.transport(ECHO_LLM, model="gpt-4o-mini")

        drain(transport.complete("system prompt", "text"))

        self.assertEqual(
            recorded_argv(binary),
            ["prompt", "-s", "system prompt", "-m", "gpt-4o-mini"],
        )

    def test_invocation_without_model(self) -> None:
        transport, binary = self.transport(ECHO_LLM)

        drain(transport.complete("system prompt", "text"))

        self.assertEqual(recorded_argv(binary), ["prompt", "-s", "system prompt"])

    def test_failure_reports_stderr(self) -> None:
        transport, _ = self.transport(FAILING_LLM)

        with self.assertRaisesRegex(RuntimeError, "Unknown model: nonexistent"):
            drain(transport.complete("s", "u"))

    def test_missing_binary(self) -> None:
        transport = LlmCliTransport(LlmOptions(binary=str(self.workdir / "nope")))

        with self.assertRaisesRegex(FileNotFoundError, "llm binary not found"):
            drain(transport.complete("s", "u"))


class LlmPluginTest(unittest.TestCase):
    def test_implements_text_tasks(self) -> None:
        triples = __glados_plugin__("llm", {"model": "m"})

        self.assertEqual(
            [(task, protocol) for task, protocol, _ in triples],
            [("rewrite", Rewriter), ("summarize", Summarizer), ("expand", Expander)],
        )
        for _, protocol, backend in triples:
            self.assertIsInstance(backend, protocol)

    def test_rejects_unknown_options(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            __glados_plugin__("llm", {"api_key": "secret"})


class LlmIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = require_settings("GLADOS_TEST_LLM_MODEL")

    def test_completes(self) -> None:
        options = LlmOptions(
            model=self.settings["GLADOS_TEST_LLM_MODEL"],
            binary=self.settings.get("GLADOS_TEST_LLM_BINARY", "llm"),
        )

        _, result = drain(LlmCliTransport(options).complete(PING_SYSTEM, "ping"))

        self.assertIn("pong", (result or "").lower())


if __name__ == "__main__":
    unittest.main()
