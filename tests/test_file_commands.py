"""oddjob's file commands through click's CliRunner."""

import json
import logging
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

import rich_click as click
from click.testing import CliRunner, Result
from support import recorded_argv, write_executable
from test_conversions import FAKE_WRITER
from test_file_domain import HAS_PILLOW, JPEG, MP4
from test_llm import ECHO_LLM

from oddjob.cli import cli
from oddjob.lib import motionphotos, renamers


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
        for name in ("filejobs", "oddjob"):  # -v changes them process-wide
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def test_hash_rename_dry_run_changes_nothing(self) -> None:
        file = self.tmp / "x.txt"
        file.write_bytes(b"hello")
        result = self.runner.invoke(cli, ["rename-by-hash", "-n", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(f"mv {file} {self.tmp / '3610a686.txt'}", result.output)
        self.assertTrue(file.exists())

    def test_batch_failure_exits_1_after_processing_the_rest(self) -> None:
        for name in ("a.txt", "b.txt"):
            (self.tmp / name).write_bytes(b"same")
        (self.tmp / "c.dat").write_bytes(b"other")
        result = self.runner.invoke(cli, ["rename-by-hash", str(self.tmp)])
        self.assertEqual(result.exit_code, 1, result.output)
        names = {p.name for p in self.tmp.iterdir()}
        self.assertIn(renamers.file_digest(self.tmp / "b.txt", "crc32") + ".txt", names)
        self.assertNotIn("c.dat", names)
        self.assertIn("2 done, 1 failed", result.output)

    def test_clean_tree_is_silent(self) -> None:
        (self.tmp / "a.jpg").write_bytes(b"a")
        for command in ("fix-extensions", "rename-by-hash"):
            with self.subTest(command=command):
                if command == "rename-by-hash":
                    name = renamers.file_digest(self.tmp / "a.jpg", "crc32") + ".jpg"
                    (self.tmp / "a.jpg").rename(self.tmp / name)
                result = self.runner.invoke(cli, [command, str(self.tmp)])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(result.output, "")

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
                cli, ["motionphotos", "merge", "-v", "-y", str(self.tmp)]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            motionphotos.split((self.tmp / "a.jpg").read_bytes()), (JPEG, MP4)
        )
        self.assertTrue((self.tmp / "a.mp4").exists())
        self.assertEqual(wrote(logs.records), [self.tmp / "a.jpg"])
        self.assertEqual(result.stdout, "")

    def test_motionphotos_merge_needs_overwrite(self) -> None:
        (self.tmp / "a.jpg").write_bytes(JPEG)
        (self.tmp / "a.mp4").write_bytes(MP4)
        refused = self.runner.invoke(cli, ["motionphotos", "merge", str(self.tmp)])
        self.assertEqual(refused.exit_code, 2, refused.output)
        self.assertIn("add -y", refused.stderr)
        self.assertEqual((self.tmp / "a.jpg").read_bytes(), JPEG)
        planned = self.runner.invoke(
            cli, ["motionphotos", "merge", "-n", str(self.tmp)]
        )
        self.assertEqual(planned.exit_code, 0, planned.output)

    def test_motionphotos_join_and_split(self) -> None:
        (self.tmp / "still.jpg").write_bytes(JPEG)
        (self.tmp / "clip.mp4").write_bytes(MP4)
        joined = self.tmp / "joined.jpg"
        with self.assertLogs("filejobs", "INFO") as join_logs:
            join = self.runner.invoke(
                cli,
                [
                    "motionphotos", "join", "-v",
                    "-i", str(self.tmp / "still.jpg"),
                    "--video", str(self.tmp / "clip.mp4"),
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
                    "motionphotos", "split", "-v", str(joined),
                    "-i", str(self.tmp / "s.jpg"),
                    "--video", str(self.tmp / "s.mp4"),
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
                cli, ["motionphotos", "strip", "-v", str(file)]
            )
        self.assertEqual(refused.exit_code, 2)
        self.assertIn("add -y", refused.stderr)
        with self.assertLogs("filejobs", "INFO") as logs:
            done = self.runner.invoke(
                cli, ["motionphotos", "strip", "-v", "-y", str(file)]
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
                cli, ["jpgize", "-v", str(self.tmp / "a.png")], env={"PATH": str(tools)}
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((self.tmp / "a.jpg").exists())
        self.assertEqual(wrote(logs.records), [self.tmp / "a.jpg"])
        self.assertEqual(result.stdout, "")


@unittest.skipUnless(HAS_PILLOW, "needs the images extra (Pillow)")
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
        result = CliRunner().invoke(cli, ["img-trim", "-n", str(tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout, f"{tmp / 'logo.png'} -> {tmp / 'logo.cropped.png'}\n"
        )


@unittest.skipUnless(HAS_PILLOW, "needs the images extra (Pillow)")
class AutocropCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        logo = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        logo.paste((0, 0, 255, 255), (2, 2, 6, 8))
        logo.save(self.tmp / "logo.png")
        Image.new("RGB", (4, 4)).save(self.tmp / "photo.jpg")
        self.runner = CliRunner()
        for name in ("filejobs", "oddjob"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def test_writes_the_cropped_image_silently(self) -> None:
        from PIL import Image

        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(
                cli, ["img-trim", "-v", str(self.tmp / "logo.png")]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        cropped = self.tmp / "logo.cropped.png"
        self.assertEqual(wrote(logs.records), [cropped])
        with Image.open(cropped) as image:
            self.assertEqual(image.size, (4, 6))

    def test_an_image_without_transparency_fails_and_the_rest_runs(self) -> None:
        result = self.runner.invoke(cli, ["img-trim", str(self.tmp)])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("1 done, 1 failed", result.stderr)
        self.assertTrue((self.tmp / "logo.cropped.png").exists())
        self.assertFalse((self.tmp / "photo.cropped.jpg").exists())


class ImgReduceDryRunTests(unittest.TestCase):
    def test_dry_run_prints_the_plan_without_decoding(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("a.jpg", "a.reduced.jpg", "b.gif", "notes.txt"):
            (tmp / name).write_bytes(b"not decoded by -n")
        runner = CliRunner()
        result = runner.invoke(cli, ["img-reduce", "-n", str(tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, f"{tmp / 'a.jpg'} -> {tmp / 'a.reduced.jpg'}\n")
        in_place = runner.invoke(cli, ["img-reduce", "-n", "--in-place", str(tmp)])
        self.assertEqual(in_place.stdout, f"{tmp / 'a.jpg'} -> {tmp / 'a.jpg'}\n")

    def test_in_place_excludes_output(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "a.jpg").write_bytes(b"x")
        result = CliRunner().invoke(
            cli, ["img-reduce", "--in-place", "-o", str(tmp / "b.jpg"), str(tmp)]
        )
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("mutually exclusive", result.output)


@unittest.skipUnless(HAS_PILLOW, "needs the images extra (Pillow)")
class ImgReduceCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        Image.new("RGB", (40, 20), (200, 10, 10)).save(self.tmp / "big.jpg")
        Image.new("RGB", (8, 8)).save(self.tmp / "small.png")
        self.runner = CliRunner()
        for name in ("filejobs", "oddjob"):
            logger = logging.getLogger(name)
            self.addCleanup(logger.setLevel, logger.level)

    def size_of(self, path: Path) -> tuple[int, int]:
        from PIL import Image

        with Image.open(path) as image:
            return image.size

    def test_writes_reduced_images_and_skips_the_ones_that_fit(self) -> None:
        with self.assertLogs("filejobs", "INFO") as logs:
            result = self.runner.invoke(
                cli, ["img-reduce", "-v", "--max-size", "10", str(self.tmp)]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.stdout, "")
        reduced = self.tmp / "big.reduced.jpg"
        self.assertEqual(wrote(logs.records), [reduced])
        self.assertEqual(self.size_of(reduced), (10, 5))
        self.assertEqual(self.size_of(self.tmp / "big.jpg"), (40, 20))
        self.assertFalse((self.tmp / "small.reduced.png").exists())

    def test_in_place_replaces_the_input(self) -> None:
        big = self.tmp / "big.jpg"
        result = self.runner.invoke(
            cli, ["img-reduce", "--in-place", "--max-size", "10", str(big)]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.size_of(big), (10, 5))
        self.assertEqual(
            sorted(p.name for p in self.tmp.iterdir()), ["big.jpg", "small.png"]
        )

    def test_existing_output_needs_y_and_an_undecodable_image_fails(self) -> None:
        (self.tmp / "big.reduced.jpg").write_bytes(b"old")
        (self.tmp / "broken.jpg").write_bytes(b"not an image")
        failed = self.runner.invoke(
            cli, ["img-reduce", "--max-size", "10", str(self.tmp)]
        )
        self.assertEqual(failed.exit_code, 1, failed.output)
        self.assertIn("1 done, 2 failed", failed.stderr)
        self.assertEqual((self.tmp / "big.reduced.jpg").read_bytes(), b"old")
        replaced = self.runner.invoke(
            cli, ["img-reduce", "-y", "--max-size", "10", str(self.tmp / "big.jpg")]
        )
        self.assertEqual(replaced.exit_code, 0, replaced.output)
        self.assertEqual(self.size_of(self.tmp / "big.reduced.jpg"), (10, 5))


class ImgEmbedDescriptionCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.image = self.tmp / "a.jpg"
        self.image.write_bytes(JPEG)
        self.sidecar = self.tmp / "a.description.txt"
        self.sidecar.write_text("a cat\n", encoding="utf-8")
        self.bare = self.tmp / "b.jpg"
        self.bare.write_bytes(JPEG)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.runner = CliRunner()
        self.env = {
            "PATH": str(self.bin),
            "XDG_CONFIG_HOME": str(self.tmp / "config"),
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
            "LC_ALL": "C",
        }

    def with_fake_llm(self) -> Path:
        llm = write_executable(self.bin, "llm", ECHO_LLM)
        config = self.tmp / "config" / "oddjob"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(
            f'[tasks]\ndescribe = "llm"\n\n[backends.llm]\nbinary = "{llm}"\n',
            encoding="utf-8",
        )
        return llm

    def test_dry_run_needs_no_exiftool_or_backend(self) -> None:
        result = self.runner.invoke(
            cli, ["img-embed-description", "-n", str(self.tmp)], env=self.env
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            result.stdout,
            f"embed {self.sidecar} into {self.image}\n"
            f"describe {self.bare} into {self.tmp / 'b.description.txt'},"
            " then embed it\n",
        )

    def test_in_place_needs_overwrite(self) -> None:
        write_executable(self.bin, "exiftool", FAKE_WRITER)
        refused = self.runner.invoke(
            cli, ["img-embed-description", str(self.tmp)], env=self.env
        )
        self.assertEqual(refused.exit_code, 2, refused.output)
        self.assertIn("add -y", refused.stderr)
        self.assertEqual(self.image.read_bytes(), JPEG)

    def test_embeds_existing_sidecars_and_describes_the_rest(self) -> None:
        write_executable(self.bin, "exiftool", FAKE_WRITER)
        self.with_fake_llm()
        done = self.runner.invoke(
            cli, ["img-embed-description", "-y", str(self.tmp)], env=self.env
        )
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertEqual(done.stdout, "")
        self.assertEqual(self.image.read_bytes(), b"converted")
        self.assertEqual(self.bare.read_bytes(), b"converted")
        self.assertEqual(self.sidecar.read_text(encoding="utf-8"), "a cat\n")
        generated = (self.tmp / "b.description.txt").read_text(encoding="utf-8")
        self.assertTrue(generated.startswith("Describe the image"))

    def test_no_backend_is_needed_when_every_image_has_a_sidecar(self) -> None:
        write_executable(self.bin, "exiftool", FAKE_WRITER)
        self.bare.unlink()
        done = self.runner.invoke(
            cli, ["img-embed-description", "-y", str(self.tmp)], env=self.env
        )
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertEqual(self.image.read_bytes(), b"converted")

    def test_redescribe_replaces_the_sidecar(self) -> None:
        write_executable(self.bin, "exiftool", FAKE_WRITER)
        self.with_fake_llm()
        self.bare.unlink()
        done = self.runner.invoke(
            cli,
            ["img-embed-description", "-y", "--redescribe", str(self.tmp)],
            env=self.env,
        )
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertTrue(
            self.sidecar.read_text(encoding="utf-8").startswith("Describe the image")
        )


# exiftool keeping each file's tags in `<file>.tags` (JSON): -json prints
# them, -TAG=VALUE arguments store them; a stored FAIL tag makes it fail.
FAKE_EXIFTOOL = """\
import json, sys
from pathlib import Path
args = sys.argv[1:]
Path(__file__).with_suffix(".argv").write_text(json.dumps(args))
target = Path(args[-1])
store = target.with_name(target.name + ".tags")
tags = json.loads(store.read_text()) if store.exists() else {}
if "FAIL" in tags:
    sys.exit("boom")
if "-json" in args:
    print(json.dumps([{"SourceFile": str(target), **tags}]))
else:
    tags.update(arg[1:].split("=", 1) for arg in args if "=" in arg)
    store.write_text(json.dumps(tags))
"""


def make_shotwell_db(
    database: Path, photos: dict[Path, int], videos: dict[Path, int]
) -> Path:
    """A minimal Shotwell library: the two tables date-copy reads."""
    with closing(sqlite3.connect(database)) as connection, connection:
        for table, rows in (("PhotoTable", photos), ("VideoTable", videos)):
            connection.execute(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, filename TEXT,"
                " exposure_time INTEGER)"
            )
            connection.executemany(
                f"INSERT INTO {table} (filename, exposure_time) VALUES (?, ?)",
                [(str(path.absolute()), time) for path, time in rows.items()],
            )
    return database


class DateSyncCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.photos = self.tmp / "photos"
        self.photos.mkdir()
        self.runner = CliRunner()
        self.when = datetime(2019, 7, 14, 18, 3, 22).astimezone()

    def photo(self, name: str, tags: dict[str, str] | None = None) -> Path:
        path = self.photos / name
        path.write_bytes(name.encode())
        os.utime(path, (0, 0))
        if tags is not None:
            path.with_name(f"{name}.tags").write_text(json.dumps(tags))
        return path

    def exiftool(self) -> Path:
        return write_executable(self.bin, "exiftool", FAKE_EXIFTOOL)

    def invoke(self, *args: str) -> Result:
        return self.runner.invoke(
            cli, ["date-copy", *args, str(self.photos)], env={"PATH": str(self.bin)}
        )

    def dated(self, path: Path) -> Path:
        digest = renamers.file_digest(path, "crc32")
        return path.with_name(f"2019-07-14 18.03.22 {digest}.jpg")

    def test_dry_run_from_mtime_needs_no_exiftool(self) -> None:
        photo = self.photo("IMG_1.JPEG")
        os.utime(photo, (0, self.when.timestamp()))
        result = self.invoke("--from", "mtime", "--to", "name", "-n")
        self.assertEqual(result.exit_code, 0, result.output)
        # The dated name has spaces: quoted, so the line can be pasted.
        self.assertEqual(result.stdout, f"mv {photo} '{self.dated(photo)}'\n")
        self.assertTrue(photo.exists())

    def test_from_exif_to_name_renames_and_fails_files_without_a_date(self) -> None:
        self.exiftool()
        dated = self.photo("a.jpg", {"DateTimeOriginal": "2019:07:14 18:03:22"})
        expected = self.dated(dated)
        undated = self.photo("b.jpg", {})
        result = self.invoke("--from", "exif", "--to", "name")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(result.stdout, "")
        self.assertIn("1 done, 1 failed", result.stderr)
        self.assertTrue(expected.exists())
        self.assertTrue(undated.exists())
        fallback = self.invoke("--from", "exif", "--to", "name", "--mtime-fallback")
        self.assertEqual(fallback.exit_code, 0, fallback.output)
        self.assertFalse(undated.exists())

    def test_to_exif_needs_y_and_writes_video_track_dates(self) -> None:
        exiftool = self.exiftool()
        name = "2019-07-14 18.03.22 0000abcd"
        self.photo(f"{name}.jpg")
        video = self.photo(f"{name}.mp4")
        refused = self.invoke("--from", "name", "--to", "exif")
        self.assertEqual(refused.exit_code, 2, refused.output)
        self.assertIn("add -y", refused.output)
        offset = self.when.strftime("%:z")
        planned = self.invoke("--from", "name", "--to", "exif", "-n")
        self.assertIn(
            f"exiftool '-AllDates=2019:07:14 18:03:22{offset}'", planned.stdout
        )
        done = self.invoke("--from", "name", "--to", "exif", "-y")
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertEqual(done.stdout, "")
        video_tags = json.loads(video.with_name(f"{name}.mp4.tags").read_text())
        self.assertEqual(video_tags["TrackCreateDate"], f"2019:07:14 18:03:22{offset}")
        image_tags = json.loads((self.photos / f"{name}.jpg.tags").read_text())
        self.assertEqual(
            image_tags,
            {
                "AllDates": "2019:07:14 18:03:22",
                "OffsetTimeOriginal": offset,
                "OffsetTimeDigitized": offset,
                "OffsetTime": offset,
            },
        )
        self.assertIn("-preserve", recorded_argv(exiftool))

    def test_from_name_to_mtime_with_a_name_format(self) -> None:
        photo = self.photo("IMG_20190714_180322.jpg")
        args = ("--from", "name", "--to", "mtime", "--name-format", "IMG_%Y%m%d_%H%M%S")
        result = self.invoke(*args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(photo.stat().st_mtime, self.when.timestamp())
        again = self.invoke(*args, "-n")
        self.assertEqual((again.exit_code, again.stdout), (0, ""))

    def test_from_shotwell_reads_the_library_read_only(self) -> None:
        listed = self.photo("a.jpg")
        unlisted = self.photo("b.mp4")
        clip = self.photo("c.mp4")
        database = make_shotwell_db(
            self.tmp / "photo.db",
            photos={listed: int(self.when.timestamp())},
            videos={clip: 0},  # Shotwell's "no time"
        )
        before = database.read_bytes()
        args = ("--from", "shotwell", "--to", "mtime", "--shotwell-db", str(database))
        planned = self.invoke(*args, "-n")
        self.assertEqual(planned.exit_code, 1, planned.output)
        self.assertEqual(
            planned.stdout,
            f"touch -m -d '2019-07-14 18:03:22' {listed}\n",
        )
        self.assertIn("1 done, 2 failed", planned.stderr)
        done = self.invoke(*args, "--mtime-fallback")
        self.assertEqual(done.exit_code, 0, done.output)
        self.assertEqual(listed.stat().st_mtime, self.when.timestamp())
        self.assertEqual(unlisted.stat().st_mtime, 0)
        self.assertEqual(database.read_bytes(), before)

    def test_shotwell_is_only_a_source_and_needs_its_database(self) -> None:
        self.photo("a.jpg")
        as_target = self.invoke("--from", "mtime", "--to", "shotwell")
        self.assertEqual(as_target.exit_code, 2, as_target.output)
        missing = self.invoke(
            "--from", "shotwell", "--to", "mtime",
            "--shotwell-db", str(self.tmp / "nope.db"),
        )  # fmt: skip
        self.assertEqual(missing.exit_code, 1, missing.output)
        self.assertIn("Shotwell database not found", missing.output)

    def test_usage_errors(self) -> None:
        same = self.invoke("--from", "name", "--to", "name")
        self.assertEqual(same.exit_code, 2, same.output)
        bad = self.invoke("--from", "name", "--to", "mtime", "--name-format", "%Y-%q")
        self.assertEqual(bad.exit_code, 2, bad.output)
        self.assertIn("%q", bad.output)


class PhotoLintCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.photos = self.tmp / "photos"
        self.photos.mkdir()
        self.runner = CliRunner()
        self.exiftool = write_executable(self.bin, "exiftool", FAKE_EXIFTOOL)

    def photo(self, name: str, tags: dict[str, str]) -> Path:
        path = self.photos / name
        path.write_bytes(name.encode())
        path.with_name(f"{name}.tags").write_text(json.dumps(tags))
        return path

    def stored_tags(self, path: Path) -> dict[str, str]:
        return json.loads(path.with_name(f"{path.name}.tags").read_text())

    def invoke(self, *args: str) -> Result:
        return self.runner.invoke(
            cli, ["photo-lint", *args, str(self.photos)], env={"PATH": str(self.bin)}
        )

    def test_check_lists_photos_without_a_zone(self) -> None:
        bare = self.photo("a.jpg", {"DateTimeOriginal": "2019:07:14 18:03:22"})
        self.photo(
            "b.jpg",
            {"DateTimeOriginal": "2019:07:14 18:03:22", "OffsetTimeOriginal": "+02:00"},
        )
        self.photo("c.jpg", {})
        result = self.invoke("check")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(result.stdout, f"{bare}: no-zone\n")
        (self.photos / "a.jpg.tags").write_text(
            json.dumps({"DateTimeOriginal": "2019:07:14 18:03:22", "FAIL": "1"})
        )
        failed = self.invoke("check")
        self.assertEqual((failed.exit_code, failed.stdout), (1, ""))
        self.assertIn("2 done, 1 failed", failed.stderr)

    def test_check_passes_clean_photos(self) -> None:
        self.photo(
            "b.jpg",
            {"DateTimeOriginal": "2019:07:14 18:03:22", "OffsetTimeOriginal": "+02:00"},
        )
        result = self.invoke("check")
        self.assertEqual((result.exit_code, result.stdout), (0, ""))

    def test_set_zone_needs_y_and_a_known_zone(self) -> None:
        self.photo("a.jpg", {"DateTimeOriginal": "2019:07:14 18:03:22"})
        refused = self.invoke("set-zone", "--zone", "Europe/Madrid")
        self.assertEqual(refused.exit_code, 2, refused.output)
        self.assertIn("add -y", refused.output)
        unknown = self.invoke("set-zone", "--zone", "Europe/Atlantis", "-y")
        self.assertEqual(unknown.exit_code, 2, unknown.output)
        self.assertIn("Europe/Atlantis", unknown.output)

    def test_set_zone_plans_then_writes_offsets(self) -> None:
        summer = self.photo("a.jpg", {"DateTimeOriginal": "2019:07:14 18:03:22"})
        winter = self.photo("b.jpg", {"CreateDate": "2019:01:14 18:03:22"})
        zoned = self.photo(
            "c.jpg",
            {"DateTimeOriginal": "2019:07:14 18:03:22", "OffsetTimeOriginal": "+05:00"},
        )
        planned = self.invoke("set-zone", "--zone", "europe/madrid", "-n")
        self.assertEqual(planned.exit_code, 0, planned.output)
        self.assertEqual(
            planned.stdout,
            f"exiftool -OffsetTimeOriginal=+02:00 {summer}\n"
            f"exiftool -OffsetTimeDigitized=+01:00 {winter}\n",
        )
        self.assertNotIn("OffsetTimeOriginal", self.stored_tags(summer))
        done = self.invoke("set-zone", "--zone", "Europe/Madrid", "-y")
        self.assertEqual((done.exit_code, done.stdout), (0, ""), done.output)
        self.assertEqual(self.stored_tags(summer)["OffsetTimeOriginal"], "+02:00")
        self.assertEqual(self.stored_tags(winter)["OffsetTimeDigitized"], "+01:00")
        self.assertEqual(self.stored_tags(zoned)["OffsetTimeOriginal"], "+05:00")
        self.assertIn("-preserve", recorded_argv(self.exiftool))
        replaced = self.invoke("set-zone", "--zone", "Europe/Madrid", "-y", "--replace")
        self.assertEqual(replaced.exit_code, 0, replaced.output)
        self.assertEqual(self.stored_tags(zoned)["OffsetTimeOriginal"], "+02:00")

    def test_set_zone_fails_skipped_hour_and_undated_photos(self) -> None:
        self.photo("a.jpg", {"DateTimeOriginal": "2024:03:31 02:30:00"})
        self.photo("b.jpg", {})
        good = self.photo("c.jpg", {"DateTimeOriginal": "2019:07:14 18:03:22"})
        result = self.invoke("set-zone", "--zone", "Europe/Madrid", "-y")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("1 done, 2 failed", result.stderr)
        self.assertEqual(self.stored_tags(good)["OffsetTimeOriginal"], "+02:00")


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
        result = self.runner.invoke(cli, ["cleanup", "-n", "--perms", str(self.tmp)])
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
        result = self.runner.invoke(cli, ["cleanup", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output, "")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["a.jpg"])
        self.assertEqual((self.tmp / "a.jpg").stat().st_mode & 0o777, 0o600)
        again = self.runner.invoke(cli, ["cleanup", str(self.tmp)])
        self.assertEqual(again.output, "")

    def test_perms_chmods(self) -> None:
        result = self.runner.invoke(cli, ["cleanup", "--perms", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual((self.tmp / "a.jpg").stat().st_mode & 0o777, 0o644)

    def test_a_failed_removal_exits_1_after_the_rest(self) -> None:
        locked = self.tmp / "locked"
        locked.mkdir()
        (locked / "Thumbs.db").write_bytes(b"junk")
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o755)
        result = self.runner.invoke(cli, ["cleanup", str(self.tmp)])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("2 done, 1 failed", result.stderr)
        self.assertFalse((self.tmp / ".DS_Store").exists())


def leaf_commands(
    group: click.Group, prefix: str = ""
) -> list[tuple[str, click.Command]]:
    """Every runnable command under `group`, with its full name."""
    found = []
    for name, command in group.commands.items():
        full = f"{prefix}{name}"
        if isinstance(command, click.Group):
            found.extend(leaf_commands(command, f"{full} "))
        else:
            found.append((full, command))
    return found


class CommandTreeTests(unittest.TestCase):
    def test_no_command_declares_an_option_twice(self) -> None:
        for name, command in leaf_commands(cli):
            with self.subTest(command=name):
                opts = [
                    opt
                    for param in command.params
                    for opt in (*param.opts, *param.secondary_opts)
                    if opt.startswith("-")
                ]
                self.assertEqual(len(opts), len(set(opts)), opts)

    def test_every_command_takes_the_logging_options(self) -> None:
        # audio-grep passes -v/-q on to grep; it takes only --log-level.
        for name, command in leaf_commands(cli):
            with self.subTest(command=name):
                names = {param.name for param in command.params}
                expected = {"log_level"}
                if name != "audio-grep":
                    expected |= {"verbose", "quiet"}
                self.assertLessEqual(expected, names)


class TextTasksInPlaceTests(unittest.TestCase):
    """--in-place on the text tasks (decision 0010), checked through -n,
    which needs no backend."""

    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.note = self.tmp / "note.txt"
        self.note.write_text("hello", encoding="utf-8")
        self.runner = CliRunner()

    def test_plan_lands_on_the_input(self) -> None:
        for command in ("rewrite", "summarize", "expand"):
            with self.subTest(command=command):
                result = self.runner.invoke(
                    cli, [command, "-n", "--in-place", str(self.note)]
                )
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(result.stdout, f"{self.note} -> {self.note}\n")

    def test_in_place_excludes_output(self) -> None:
        for command in ("rewrite", "summarize", "expand", "translate"):
            with self.subTest(command=command):
                required = ["-l", "es"] if command == "translate" else []
                args = [command, *required, "--in-place"]
                args += ["-o", str(self.tmp / "b.txt")]
                result = self.runner.invoke(cli, [*args, str(self.note)])
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn("mutually exclusive", result.output)

    def test_only_same_format_commands_take_in_place(self) -> None:
        for command in ("jpgize", "mp4ize", "describe"):
            with self.subTest(command=command):
                result = self.runner.invoke(cli, [command, "--in-place", str(self.tmp)])
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn("No such option", result.output)

    def test_keep_mtime_is_offered_by_every_file_producer(self) -> None:
        for command in ("img-trim", "img-reduce", "jpgize", "mp4ize", "rewrite"):
            with self.subTest(command=command):
                result = self.runner.invoke(cli, [command, "--help"])
                self.assertIn("--keep-mtime", result.output)


if __name__ == "__main__":
    unittest.main()
