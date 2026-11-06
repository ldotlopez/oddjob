"""Unit tests for the backend-free core shared with multitool: input
expansion, batch runs and destination checks."""

import tempfile
import unittest
from pathlib import Path

from glados.core.batch import run_batch
from glados.core.inputs import accept_all, expand_inputs
from glados.core.pipeline import check_destination, move_to_destination


class ExpandInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
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


class RunBatchTests(unittest.TestCase):
    def test_failures_are_recorded_and_the_rest_still_run(self) -> None:
        seen: list[int] = []

        def action(item: int) -> None:
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
        def action(item: int) -> None:
            raise KeyError(item)

        with self.assertRaises(KeyError):
            run_batch([1], action, description="Testing")


class DestinationTests(unittest.TestCase):
    def test_existing_destination_needs_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            produced, dest = Path(tmp, "new"), Path(tmp, "dest")
            produced.write_text("new")
            dest.write_text("old")
            with self.assertRaises(FileExistsError):
                check_destination(dest, overwrite=False)
            move_to_destination(produced, dest, overwrite=True)
            self.assertEqual(dest.read_text(), "new")
            self.assertFalse(produced.exists())


if __name__ == "__main__":
    unittest.main()
