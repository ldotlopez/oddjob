"""multitool commands through click's CliRunner."""

import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner
from support import write_executable
from test_multitool_conversions import FAKE_WRITER
from test_multitool_domain import JPEG, MP4

from multitool import motionphotos, renamers
from multitool.cli import cli


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runner = CliRunner()

    def test_hash_rename_dry_run_changes_nothing(self) -> None:
        file = self.tmp / "x.txt"
        file.write_bytes(b"hello")
        result = self.runner.invoke(cli, ["hash-rename", "-n", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(f"mv {file} {self.tmp / '3610a686.txt'}", result.output)
        self.assertTrue(file.exists())

    def test_batch_failure_exits_1_after_processing_the_rest(self) -> None:
        for name in ("a.txt", "b.txt"):
            (self.tmp / name).write_bytes(b"same")
        (self.tmp / "c.dat").write_bytes(b"other")
        result = self.runner.invoke(cli, ["hash-rename", str(self.tmp)])
        self.assertEqual(result.exit_code, 1, result.output)
        names = {p.name for p in self.tmp.iterdir()}
        self.assertIn(renamers.file_digest(self.tmp / "b.txt", "crc32") + ".txt", names)
        self.assertNotIn("c.dat", names)

    def test_motionphotos_merge_keeps_video_unless_rm(self) -> None:
        (self.tmp / "a.jpg").write_bytes(JPEG)
        (self.tmp / "a.mp4").write_bytes(MP4)
        result = self.runner.invoke(cli, ["motionphotos", "merge", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            motionphotos.split((self.tmp / "a.jpg").read_bytes()), (JPEG, MP4)
        )
        self.assertTrue((self.tmp / "a.mp4").exists())
        self.assertIn(f"Wrote {self.tmp / 'a.jpg'}", result.output)

    def test_motionphotos_join_and_split(self) -> None:
        (self.tmp / "still.jpg").write_bytes(JPEG)
        (self.tmp / "clip.mp4").write_bytes(MP4)
        joined = self.tmp / "joined.jpg"
        join = self.runner.invoke(
            cli,
            [
                "motionphotos", "join",
                "-i", str(self.tmp / "still.jpg"),
                "-v", str(self.tmp / "clip.mp4"),
                "-o", str(joined),
                "--rm",
            ],
        )  # fmt: skip
        self.assertEqual(join.exit_code, 0, join.output)
        self.assertFalse((self.tmp / "clip.mp4").exists())
        split = self.runner.invoke(
            cli,
            [
                "motionphotos", "split", str(joined),
                "-i", str(self.tmp / "s.jpg"),
                "-v", str(self.tmp / "s.mp4"),
            ],
        )  # fmt: skip
        self.assertEqual(split.exit_code, 0, split.output)
        self.assertEqual((self.tmp / "s.jpg").read_bytes(), JPEG)
        self.assertEqual((self.tmp / "s.mp4").read_bytes(), MP4)

    def test_motionphotos_check_exit_status(self) -> None:
        (self.tmp / "still.jpg").write_bytes(JPEG)
        (self.tmp / "motion.jpg").write_bytes(motionphotos.join(JPEG, MP4))
        check = ["motionphotos", "check"]
        motion = self.runner.invoke(cli, [*check, str(self.tmp / "motion.jpg")])
        still = self.runner.invoke(cli, [*check, str(self.tmp / "still.jpg")])
        self.assertEqual((motion.exit_code, still.exit_code), (0, 1))

    def test_strip_in_place_needs_overwrite(self) -> None:
        file = self.tmp / "motion.jpg"
        file.write_bytes(motionphotos.join(JPEG, MP4))
        refused = self.runner.invoke(cli, ["motionphotos", "strip", str(file)])
        self.assertEqual(refused.exit_code, 1)
        done = self.runner.invoke(cli, ["motionphotos", "strip", "-y", str(file)])
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertEqual(file.read_bytes(), JPEG)

    def test_sidecars_scan_needs_two_extensions(self) -> None:
        result = self.runner.invoke(
            cli, ["sidecars", "scan", str(self.tmp), "-e", "jpg"]
        )
        self.assertEqual(result.exit_code, 2)

    def test_conversion_dry_run_needs_no_tools(self) -> None:
        (self.tmp / "a.png").write_bytes(b"png")
        result = self.runner.invoke(cli, ["jpgize", "-n", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(
            f"convert {self.tmp / 'a.png'} -> {self.tmp / 'a.jpg'}", result.output
        )

    def test_jpgize_prints_what_it_wrote(self) -> None:
        tools = self.tmp / "bin"
        tools.mkdir()
        for name in ("magick", "exiftool"):
            write_executable(tools, name, FAKE_WRITER)
        (self.tmp / "a.png").write_bytes(b"png")
        result = self.runner.invoke(
            cli, ["jpgize", str(self.tmp / "a.png")], env={"PATH": str(tools)}
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(f"Wrote {self.tmp / 'a.jpg'}", result.output)


if __name__ == "__main__":
    unittest.main()
