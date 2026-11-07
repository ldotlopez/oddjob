"""Unit tests for the transcribe task's output-format resolution."""

import unittest
from pathlib import Path

from oddjob.commands.transcribe import resolve_output_format
from oddjob.lib.transcribe import DEFAULT_OUTPUT_FORMAT


class ResolveOutputFormatTests(unittest.TestCase):
    def test_default_is_plain_text(self) -> None:
        self.assertEqual(DEFAULT_OUTPUT_FORMAT, "txt")
        self.assertEqual(resolve_output_format(None, None), "txt")

    def test_explicit_format_wins_over_output_extension(self) -> None:
        self.assertEqual(resolve_output_format("vtt", Path("talk.srt")), "vtt")

    def test_known_output_extension_selects_format(self) -> None:
        self.assertEqual(resolve_output_format(None, Path("subs/talk.SRT")), "srt")

    def test_unknown_output_extension_falls_back_to_default(self) -> None:
        self.assertEqual(resolve_output_format(None, Path("talk.transcript")), "txt")
        self.assertEqual(resolve_output_format(None, Path("talk")), "txt")


if __name__ == "__main__":
    unittest.main()
