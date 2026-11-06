"""describe: the step, its prompt, and the command end to end through the llm
backend's fake executable."""

import logging
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner
from support import NullReporter, recorded_argv, write_executable
from test_llm import ECHO_LLM

from filejobs.pipeline import Job, suffix_destination
from filejobs.progress import ProgressEvent, ProgressStream
from glados.commands import describe
from glados.core.config import Prompts
from glados.tasks.describe import DESCRIPTION_EXTENSION, DescribeStep


class FakeDescriber:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str]] = []

    def describe(self, image: Path, *, prompt: str) -> ProgressStream[str]:
        self.calls.append((image, prompt))
        yield ProgressEvent(completed=3, total=None)
        yield ProgressEvent(completed=3, total=3, done=True, result="a cat")


class DescribeStepTests(unittest.TestCase):
    def test_writes_the_description_next_to_the_image(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        image = tmp / "cat.jpg"
        image.write_bytes(b"jpeg")
        describer = FakeDescriber()
        job = Job(
            steps=[(DescribeStep(describer, "the prompt"), "Describing")],
            dest_fn=suffix_destination(DESCRIPTION_EXTENSION),
        )
        dest = job.run(image, NullReporter())
        self.assertEqual(dest, tmp / "cat.description.txt")
        self.assertEqual(dest.read_text(encoding="utf-8"), "a cat")
        self.assertEqual(describer.calls, [(image, "the prompt")])

    def test_prompt_takes_optional_instructions(self) -> None:
        self.assertIn("in Spanish", Prompts().render_describe("in Spanish"))
        self.assertNotIn("{", Prompts().render_describe(None))


class DescribeCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.tmp / "cat.jpg").write_bytes(b"jpeg")
        (self.tmp / "notes.txt").write_text("not an image", encoding="utf-8")
        self.runner = CliRunner()
        for name in ("filejobs", "glados"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def test_dry_run_needs_no_backend_and_takes_only_images(self) -> None:
        no_backend = {
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "GLADOS_DESCRIBE_BACKEND": None,
        }
        result = self.runner.invoke(describe.cli, ["-n", str(self.tmp)], env=no_backend)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"{self.tmp / 'cat.jpg'} -> {self.tmp / 'cat.description.txt'}\n",
        )

    def test_describes_through_the_selected_backend_silently(self) -> None:
        llm = write_executable(self.tmp, "llm", ECHO_LLM)
        config = self.tmp / "config" / "glados"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(
            f'[tasks]\ndescribe = "llm"\n\n[backends.llm]\nbinary = "{llm}"\n',
            encoding="utf-8",
        )
        image = self.tmp / "cat.jpg"
        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(
                describe.cli,
                ["-v", "-i", "in Spanish", str(image)],
                env={"XDG_CONFIG_HOME": str(self.tmp / "config")},
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        destination = self.tmp / "cat.description.txt"
        self.assertIn(f"wrote {destination}", [r.getMessage() for r in logs.records])
        argv = recorded_argv(llm)
        self.assertEqual(argv[-2:], ["-a", str(image)])
        self.assertIn("in Spanish", argv[argv.index("-s") + 1])


if __name__ == "__main__":
    unittest.main()
