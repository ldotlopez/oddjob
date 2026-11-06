"""Unit tests for the backend-free core shared by glados' tasks and
multitool: input expansion, batch runs, BytesStep, run_jobs and the
multiple-input task commands."""

import os
import tempfile
import unittest
from pathlib import Path

import rich_click as click
from click.testing import CliRunner
from support import NullReporter

from glados.core.batch import run_batch
from glados.core.cli_options import job_action, run_jobs
from glados.core.inputs import (
    accept_all,
    expand_inputs,
    media_type_filter,
    text_inputs_except_outputs,
)
from glados.core.pipeline import (
    BytesStep,
    Job,
    check_destination,
    move_to_destination,
    suffix_destination,
)
from glados.core.progress import BaseProgressReporter
from glados.tasks import rewrite, transcribe


def make_tmp(test: unittest.TestCase) -> Path:
    return Path(test.enterContext(tempfile.TemporaryDirectory()))


class ExpandInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp(self)
        (self.tmp / "dir" / "sub").mkdir(parents=True)
        for name in (
            "dir/b.txt",
            "dir/a.txt",
            "dir/sub/c.txt",
            "dir/skip.bin",
            "x.bin",
        ):
            (self.tmp / name).write_text(name)

    def test_directories_are_walked_recursively_and_filtered(self) -> None:
        inputs = expand_inputs([self.tmp / "dir"], lambda p: p.suffix == ".txt")
        self.assertEqual(
            [p.relative_to(self.tmp).as_posix() for p in inputs],
            ["dir/a.txt", "dir/b.txt", "dir/sub/c.txt"],
        )

    def test_file_arguments_bypass_the_filter(self) -> None:
        inputs = expand_inputs([self.tmp / "x.bin"], lambda p: False)
        self.assertEqual(inputs, [self.tmp / "x.bin"])

    def test_duplicates_are_dropped_keeping_argument_order(self) -> None:
        file = self.tmp / "dir" / "a.txt"
        inputs = expand_inputs([file, self.tmp / "dir", file], accept_all)
        self.assertEqual(inputs[0], file)
        self.assertEqual(len(inputs), len(set(inputs)))

    def test_type_filters(self) -> None:
        is_media = media_type_filter("audio/", "video/")
        self.assertTrue(is_media(Path("talk.MP4")))
        self.assertTrue(is_media(Path("talk.m4a")))
        self.assertFalse(is_media(Path("talk.txt")))
        is_input = text_inputs_except_outputs("rewrite")
        self.assertTrue(is_input(Path("notes.md")))
        self.assertFalse(is_input(Path("notes.rewrite.md")))
        self.assertFalse(is_input(Path("photo.jpg")))


class RunBatchTests(unittest.TestCase):
    def test_failures_are_recorded_and_the_rest_still_run(self) -> None:
        seen: list[int] = []

        def action(item: int, _reporter: BaseProgressReporter) -> None:
            if item == 2:
                raise ValueError("bad item")
            seen.append(item)

        with self.assertLogs("glados.core.batch", level="ERROR"):
            report = run_batch([1, 2, 3], action, description="Testing")
        self.assertEqual(seen, [1, 3])
        self.assertEqual(report.succeeded, 2)
        self.assertEqual(
            [(f.item, f.reason) for f in report.failures], [("2", "bad item")]
        )

    def test_unexpected_errors_propagate(self) -> None:
        def action(item: int, _reporter: BaseProgressReporter) -> None:
            raise KeyError(item)

        with self.assertRaises(KeyError):
            run_batch([1], action, description="Testing")

    def test_step_tasks_are_removed_once_complete(self) -> None:
        def action(item: int, reporter: BaseProgressReporter) -> None:
            task_id = reporter.add_task(f"step {item}", total=1)
            reporter.update(task_id, completed=1)
            reporter.complete(task_id)

        report = run_batch([1, 2, 3], action, description="Testing")
        self.assertEqual(report.succeeded, 3)


class BytesStepAndRunJobsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp(self)
        self.inputs = []
        for name in ("a.dat", "b.dat"):
            path = self.tmp / name
            path.write_bytes(name.encode())
            os.utime(path, (1_000_000, 1_000_000))
            self.inputs.append(path)
        self.job = Job(
            steps=[(BytesStep(bytes.upper, ".out"), "Uppercasing")],
            dest_fn=suffix_destination("out"),
        )

    def test_bytes_step_keeps_timestamps(self) -> None:
        dest = self.job.run(self.inputs[0], NullReporter(), overwrite=False)
        self.assertEqual(dest.read_bytes(), b"A.DAT")
        self.assertEqual(dest.stat().st_mtime, 1_000_000)

    def test_run_jobs_continues_and_exits_1_on_failure(self) -> None:
        (self.tmp / "a.out").write_text("exists")
        runner = CliRunner()

        @click.command()
        def command() -> None:
            run_jobs(self.inputs, job_action(self.job, overwrite=False), "Testing")

        result = runner.invoke(command, [])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual((self.tmp / "b.out").read_bytes(), b"B.DAT")
        self.assertIn(f"Wrote {self.tmp / 'b.out'}", result.output)

    def test_destination_helpers(self) -> None:
        produced, dest = self.tmp / "new", self.tmp / "dest"
        produced.write_text("new")
        dest.write_text("old")
        with self.assertRaises(FileExistsError):
            check_destination(dest, overwrite=False)
        move_to_destination(produced, dest, overwrite=True)
        self.assertEqual(dest.read_text(), "new")
        self.assertFalse(produced.exists())


SHARED_MEMORY = Path("/dev/shm")


def other_filesystem(path: Path) -> Path | None:
    """A writable directory on another filesystem than `path`, if any."""
    usable = SHARED_MEMORY.is_dir() and os.access(SHARED_MEMORY, os.W_OK)
    if usable and SHARED_MEMORY.stat().st_dev != path.stat().st_dev:
        return SHARED_MEMORY
    return None


class CrossFilesystemMoveTests(unittest.TestCase):
    """move_to_destination between the temp dir and another filesystem."""

    def setUp(self) -> None:
        self.tmp = make_tmp(self)
        other = other_filesystem(self.tmp)
        if other is None:
            self.skipTest("no second writable filesystem")
        self.dest_dir = Path(self.enterContext(tempfile.TemporaryDirectory(dir=other)))

    def test_replaces_destination_and_removes_source(self) -> None:
        produced, dest = self.tmp / "new", self.dest_dir / "dest"
        produced.write_text("new")
        os.utime(produced, (1_000_000, 1_000_000))
        dest.write_text("old")
        move_to_destination(produced, dest, overwrite=True)
        self.assertEqual(dest.read_text(), "new")
        self.assertEqual(dest.stat().st_mtime, 1_000_000)
        self.assertFalse(produced.exists())
        self.assertEqual(list(self.dest_dir.iterdir()), [dest])

    def test_failed_copy_keeps_destination_and_leaves_no_temp_file(self) -> None:
        produced, dest = self.tmp / "unreadable", self.dest_dir / "dest"
        produced.mkdir()  # renaming works, copying it as a file does not
        dest.write_text("old")
        with self.assertRaises(OSError):
            move_to_destination(produced, dest, overwrite=True)
        self.assertEqual(dest.read_text(), "old")
        self.assertEqual(list(self.dest_dir.iterdir()), [dest])


class MultipleInputTaskTests(unittest.TestCase):
    """-o is rejected with several inputs before any backend is touched."""

    def test_output_needs_a_single_input(self) -> None:
        tmp = make_tmp(self)
        for name in ("a.txt", "b.txt"):
            (tmp / name).write_text("text")
        runner = CliRunner()
        for command in (rewrite.cli, transcribe.cli):
            result = runner.invoke(command, ["-o", str(tmp / "out.txt"), str(tmp)])
            self.assertEqual(result.exit_code, 2, result.output)
            self.assertIn("exactly one input file", result.output)


if __name__ == "__main__":
    unittest.main()
