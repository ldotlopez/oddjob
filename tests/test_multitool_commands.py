"""multitool commands through click's CliRunner."""

import logging
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner
from support import write_executable
from test_multitool_conversions import FAKE_WRITER
from test_multitool_domain import HAS_PILLOW, JPEG, MP4, SRT

from multitool import motionphotos, renamers
from multitool.cli import cli


def wrote(records: list[logging.LogRecord]) -> list[Path]:
    """The destinations of the `wrote <dest>` records captured by assertLogs."""
    prefix = "wrote "
    return [
        Path(message.removeprefix(prefix))
        for message in (record.getMessage() for record in records)
        if message.startswith(prefix)
    ]


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runner = CliRunner()
        for name in ("filejobs", "multitool"):  # -v changes them process-wide
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

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

    def test_fix_extensions_dry_run_changes_nothing(self) -> None:
        (self.tmp / "a.JPEG").write_bytes(b"a")
        (self.tmp / "b.jpg").write_bytes(b"b")
        result = self.runner.invoke(cli, ["fix-extensions", "-n", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout, f"mv {self.tmp / 'a.JPEG'} {self.tmp / 'a.jpg'}\n"
        )
        self.assertEqual(
            sorted(p.name for p in self.tmp.iterdir()), ["a.JPEG", "b.jpg"]
        )

    def test_fix_extensions_is_silent_and_skips_taken_names(self) -> None:
        (self.tmp / "a.TIF").write_bytes(b"new")
        (self.tmp / "b.Jpeg").write_bytes(b"b")
        (self.tmp / "a.tiff").write_bytes(b"old")
        failed = self.runner.invoke(cli, ["fix-extensions", str(self.tmp)])
        self.assertEqual(failed.exit_code, 1, failed.output)
        self.assertEqual(failed.stdout, "")
        self.assertIn("1 done, 1 failed", failed.stderr)
        names = sorted(p.name for p in self.tmp.iterdir())
        self.assertEqual(names, ["a.TIF", "a.tiff", "b.jpg"])
        replaced = self.runner.invoke(cli, ["fix-extensions", "-y", str(self.tmp)])
        self.assertEqual(replaced.exit_code, 0, replaced.output)
        self.assertEqual(replaced.stdout, "")
        self.assertEqual((self.tmp / "a.tiff").read_bytes(), b"new")

    def test_motionphotos_merge_keeps_video_unless_rm(self) -> None:
        (self.tmp / "a.jpg").write_bytes(JPEG)
        (self.tmp / "a.mp4").write_bytes(MP4)
        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(
                cli, ["-v", "motionphotos", "merge", str(self.tmp)]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            motionphotos.split((self.tmp / "a.jpg").read_bytes()), (JPEG, MP4)
        )
        self.assertTrue((self.tmp / "a.mp4").exists())
        self.assertEqual(wrote(logs.records), [self.tmp / "a.jpg"])
        self.assertEqual(result.stdout, "")

    def test_motionphotos_join_and_split(self) -> None:
        (self.tmp / "still.jpg").write_bytes(JPEG)
        (self.tmp / "clip.mp4").write_bytes(MP4)
        joined = self.tmp / "joined.jpg"
        with self.assertLogs("filejobs", "INFO") as join_logs:
            join = self.runner.invoke(
                cli,
                [
                    "-v", "motionphotos", "join",
                    "-i", str(self.tmp / "still.jpg"),
                    "-v", str(self.tmp / "clip.mp4"),
                    "-o", str(joined),
                    "--rm",
                ],
            )  # fmt: skip
        self.assertEqual(join.exit_code, 0, join.output)
        self.assertFalse((self.tmp / "clip.mp4").exists())
        self.assertEqual(wrote(join_logs.records), [joined])
        with self.assertLogs("filejobs", "INFO") as split_logs:
            split = self.runner.invoke(
                cli,
                [
                    "-v", "motionphotos", "split", str(joined),
                    "-i", str(self.tmp / "s.jpg"),
                    "-v", str(self.tmp / "s.mp4"),
                ],
            )  # fmt: skip
        self.assertEqual(split.exit_code, 0, split.output)
        self.assertEqual((self.tmp / "s.jpg").read_bytes(), JPEG)
        self.assertEqual((self.tmp / "s.mp4").read_bytes(), MP4)
        self.assertEqual(
            sorted(wrote(split_logs.records)), [self.tmp / "s.jpg", self.tmp / "s.mp4"]
        )
        self.assertEqual((join.stdout, split.stdout), ("", ""))

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
        with self.assertNoLogs("filejobs", "INFO"):
            refused = self.runner.invoke(
                cli, ["-v", "motionphotos", "strip", str(file)]
            )
        self.assertEqual(refused.exit_code, 1)
        with self.assertLogs("filejobs", "INFO") as logs:
            done = self.runner.invoke(
                cli, ["-v", "motionphotos", "strip", "-y", str(file)]
            )
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertEqual(file.read_bytes(), JPEG)
        self.assertEqual(wrote(logs.records), [file])

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

    def test_jpgize_logs_what_it_wrote(self) -> None:
        tools = self.tmp / "bin"
        tools.mkdir()
        for name in ("magick", "exiftool"):
            write_executable(tools, name, FAKE_WRITER)
        (self.tmp / "a.png").write_bytes(b"png")
        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(
                cli, ["-v", "jpgize", str(self.tmp / "a.png")], env={"PATH": str(tools)}
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((self.tmp / "a.jpg").exists())
        self.assertEqual(wrote(logs.records), [self.tmp / "a.jpg"])
        self.assertEqual(result.stdout, "")


@unittest.skipUnless(HAS_PILLOW, "needs the multitool extra (Pillow)")
class ImageCheckCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        Image.new("RGB", (16, 16), "red").save(self.tmp / "good.png")
        self.runner = CliRunner()

    def test_good_images_print_nothing(self) -> None:
        result = self.runner.invoke(cli, ["img-check", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")

    def test_corrupt_images_are_listed_on_stdout_and_exit_1(self) -> None:
        (self.tmp / "bad.jpg").write_bytes(b"not an image")
        (self.tmp / "notes.txt").write_text("not checked")
        result = self.runner.invoke(cli, ["img-check", str(self.tmp)])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(
            result.stdout.splitlines(),
            [f"{self.tmp / 'bad.jpg'}: cannot identify image file"],
        )
        self.assertNotIn("failed", result.stderr)


class AutocropDryRunTests(unittest.TestCase):
    def test_dry_run_prints_the_plan_and_skips_earlier_outputs(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("logo.png", "logo.cropped.png", "notes.txt"):
            (tmp / name).write_bytes(b"not decoded by -n")
        result = CliRunner().invoke(cli, ["autocrop", "-n", str(tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout, f"{tmp / 'logo.png'} -> {tmp / 'logo.cropped.png'}\n"
        )


@unittest.skipUnless(HAS_PILLOW, "needs the multitool extra (Pillow)")
class AutocropCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        logo = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        logo.paste((0, 0, 255, 255), (2, 2, 6, 8))
        logo.save(self.tmp / "logo.png")
        Image.new("RGB", (4, 4)).save(self.tmp / "photo.jpg")
        self.runner = CliRunner()
        for name in ("filejobs", "multitool"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def test_writes_the_cropped_image_silently(self) -> None:
        from PIL import Image

        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(
                cli, ["-v", "autocrop", str(self.tmp / "logo.png")]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        cropped = self.tmp / "logo.cropped.png"
        self.assertEqual(wrote(logs.records), [cropped])
        with Image.open(cropped) as image:
            self.assertEqual(image.size, (4, 6))

    def test_an_image_without_transparency_fails_and_the_rest_runs(self) -> None:
        result = self.runner.invoke(cli, ["autocrop", str(self.tmp)])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("1 done, 1 failed", result.stderr)
        self.assertTrue((self.tmp / "logo.cropped.png").exists())
        self.assertFalse((self.tmp / "photo.cropped.jpg").exists())


class SrtGrepCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.tmp / "meeting.srt").write_text(SRT, encoding="utf-8")
        (self.tmp / "meeting.mp4").write_bytes(MP4)
        self.runner = CliRunner()

    def test_prints_matching_cues_once_per_srt(self) -> None:
        result = self.runner.invoke(
            cli,
            ["srt-grep", "BUDGET", str(self.tmp), str(self.tmp / "meeting.mp4")],
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"{self.tmp / 'meeting.srt'} @ 00:00:01,000: The Budget for Q3\n",
        )

    def test_no_match_exits_1(self) -> None:
        result = self.runner.invoke(cli, ["srt-grep", "absent", str(self.tmp)])
        self.assertEqual((result.exit_code, result.stdout), (1, ""))

    def test_a_media_file_without_sidecar_fails_and_the_rest_runs(self) -> None:
        (self.tmp / "silent.mp4").write_bytes(MP4)
        result = self.runner.invoke(
            cli,
            ["srt-grep", "budget", str(self.tmp / "silent.mp4"), str(self.tmp)],
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("The Budget for Q3", result.stdout)
        self.assertIn("1 done, 1 failed", result.stderr)


class ImgCaptionCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.image = self.tmp / "a.jpg"
        self.image.write_bytes(JPEG)
        (self.tmp / "a.description.txt").write_text("a cat\n", encoding="utf-8")
        (self.tmp / "b.jpg").write_bytes(JPEG)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.runner = CliRunner()

    def test_dry_run_needs_no_exiftool(self) -> None:
        result = self.runner.invoke(
            cli, ["img-caption", "-n", str(self.tmp)], env={"PATH": str(self.bin)}
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"caption {self.image} from {self.tmp / 'a.description.txt'}\n",
        )

    def test_in_place_needs_overwrite(self) -> None:
        write_executable(self.bin, "exiftool", FAKE_WRITER)
        env = {"PATH": str(self.bin)}
        refused = self.runner.invoke(cli, ["img-caption", str(self.tmp)], env=env)
        self.assertEqual(refused.exit_code, 1, refused.output)
        self.assertIn("0 done, 1 failed", refused.stderr)
        self.assertEqual(self.image.read_bytes(), JPEG)
        done = self.runner.invoke(cli, ["img-caption", "-y", str(self.tmp)], env=env)
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertEqual(done.stdout, "")
        self.assertEqual(self.image.read_bytes(), b"converted")
        self.assertEqual((self.tmp / "b.jpg").read_bytes(), JPEG)


class FsCleanupCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runner = CliRunner()
        (self.tmp / "a.jpg").write_bytes(b"a")
        (self.tmp / "a.jpg").chmod(0o600)
        (self.tmp / ".DS_Store").write_bytes(b"junk")
        (self.tmp / ".Spotlight-V100").mkdir()
        (self.tmp / ".Spotlight-V100" / "store.db").write_bytes(b"junk")

    def test_dry_run_prints_the_plan_and_changes_nothing(self) -> None:
        result = self.runner.invoke(cli, ["fs-cleanup", "-n", "--perms", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"chmod 755 {self.tmp}",  # TemporaryDirectory is 700
                f"rm {self.tmp / '.DS_Store'}",
                f"rm -r {self.tmp / '.Spotlight-V100'}",
                f"chmod 644 {self.tmp / 'a.jpg'}",
            ],
        )
        self.assertTrue((self.tmp / ".DS_Store").exists())
        self.assertEqual((self.tmp / "a.jpg").stat().st_mode & 0o777, 0o600)

    def test_removes_junk_silently_and_keeps_modes_without_perms(self) -> None:
        result = self.runner.invoke(cli, ["fs-cleanup", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output, "")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["a.jpg"])
        self.assertEqual((self.tmp / "a.jpg").stat().st_mode & 0o777, 0o600)
        again = self.runner.invoke(cli, ["fs-cleanup", str(self.tmp)])
        self.assertEqual(again.output, "")

    def test_perms_chmods(self) -> None:
        result = self.runner.invoke(cli, ["fs-cleanup", "--perms", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual((self.tmp / "a.jpg").stat().st_mode & 0o777, 0o644)

    def test_a_failed_removal_exits_1_after_the_rest(self) -> None:
        locked = self.tmp / "locked"
        locked.mkdir()
        (locked / "Thumbs.db").write_bytes(b"junk")
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o755)
        result = self.runner.invoke(cli, ["fs-cleanup", str(self.tmp)])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("2 done, 1 failed", result.stderr)
        self.assertFalse((self.tmp / ".DS_Store").exists())


if __name__ == "__main__":
    unittest.main()
