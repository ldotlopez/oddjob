"""Unit tests for multitool: the domain modules, the adapters (against fake
executables) and the commands (through click's CliRunner)."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner
from foundation.cache import UserCache
from support import recorded_argv, write_executable

from glados.core.runners import FFMpegRunner
from multitool import media, motionphotos, renamers, sidecars
from multitool.cli import cli
from multitool.conversions import (
    Conversion,
    convert_to_jpeg,
    plan_conversions,
    remux_to_mp4,
)
from multitool.external import ExifTool, ImageMagick

HAS_PILLOW = importlib.util.find_spec("PIL") is not None

JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"
MP4 = b"\x00\x00\x00\x18ftypmp42fake-video"

# Records its argv, then writes the last argument as an output file.
FAKE_WRITER = """\
import json, sys
from pathlib import Path
Path(__file__).with_suffix(".argv").write_text(json.dumps(sys.argv[1:]))
Path(sys.argv[-1]).write_bytes(b"converted")
"""

# Records its argv; fails on an audio stream copy when FAIL_COPY is set.
FAKE_FFMPEG = """\
import json, os, sys
from pathlib import Path
log = Path(__file__).with_suffix(".argv")
calls = json.loads(log.read_text()) if log.exists() else []
calls.append(sys.argv[1:])
log.write_text(json.dumps(calls))
codec = sys.argv[sys.argv.index("-c:a") + 1]
if os.environ.get("FAIL_COPY") and codec == "copy":
    sys.stderr.write("codec not supported in mp4\\n")
    sys.exit(1)
Path(sys.argv[-1]).write_bytes(b"mp4")
print("progress=end")
"""


def make_tmp(test: unittest.TestCase) -> Path:
    return Path(test.enterContext(tempfile.TemporaryDirectory()))


class MediaTests(unittest.TestCase):
    def test_classification(self) -> None:
        self.assertTrue(media.is_image(Path("a.HEIC")))
        self.assertTrue(media.is_video(Path("a.3gp")))
        self.assertFalse(media.is_video(Path("a.jpg")))
        self.assertTrue(media.converts_to_jpeg(Path("a.webp")))
        self.assertFalse(media.converts_to_jpeg(Path("a.jpg")))
        self.assertTrue(media.converts_to_mp4(Path("a.mkv")))
        self.assertFalse(media.converts_to_mp4(Path("a.MP4")))


class SidecarTests(unittest.TestCase):
    FILES = (Path("d/a.jpg"), Path("d/a.MP4"), Path("d/a.xmp"), Path("d/b.jpg"))

    def test_groups_by_directory_and_stem(self) -> None:
        groups = sidecars.group_sidecars(self.FILES)
        self.assertEqual([g.base for g in groups], [Path("d/a")])
        singles = sidecars.group_sidecars(self.FILES, include_singles=True)
        self.assertEqual(len(singles), 2)

    def test_extension_filter_keeps_only_wanted_files(self) -> None:
        groups = sidecars.with_extensions(
            sidecars.group_sidecars(self.FILES), ["jpg", ".mp4"]
        )
        self.assertEqual(groups[0].files, (Path("d/a.MP4"), Path("d/a.jpg")))
        strict = sidecars.with_extensions(
            sidecars.group_sidecars(self.FILES), ["jpg", "mp4"], case_sensitive=True
        )
        self.assertEqual(strict, [])

    def test_sidecars_of(self) -> None:
        group = sidecars.sidecars_of(Path("d/a.jpg"), self.FILES)
        assert group is not None
        self.assertEqual(len(group.files), 3)
        self.assertIsNone(sidecars.sidecars_of(Path("d/b.jpg"), self.FILES))


class MotionPhotoTests(unittest.TestCase):
    def test_join_split_round_trip(self) -> None:
        joined = motionphotos.join(JPEG, MP4)
        self.assertEqual(motionphotos.split(joined), (JPEG, MP4))
        self.assertEqual(motionphotos.strip(joined), JPEG)

    def test_marker_not_followed_by_mp4_is_ignored(self) -> None:
        image = JPEG + motionphotos.MARKER + b"not a video"
        photo = motionphotos.MotionPhoto.parse(
            image + motionphotos.MARKER + MP4 + motionphotos.MARKER + b"index"
        )
        self.assertEqual(photo.image, image)
        self.assertEqual(photo.video, MP4 + motionphotos.MARKER + b"index")

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            motionphotos.split(JPEG)
        with self.assertRaises(ValueError):
            motionphotos.join(JPEG, b"not an mp4")
        with self.assertRaises(ValueError):
            motionphotos.join(motionphotos.join(JPEG, MP4), MP4)

    def test_plan_merges_needs_one_jpeg_and_one_mp4(self) -> None:
        groups = sidecars.group_sidecars(
            [Path("a.jpg"), Path("a.mp4"), Path("b.jpg"), Path("b.mov")]
        )
        merges = motionphotos.plan_merges(groups, remove_video=False)
        self.assertEqual(
            merges, [motionphotos.Merge(Path("a.jpg"), Path("a.mp4"), False)]
        )


class RenamerTests(unittest.TestCase):
    def test_digests(self) -> None:
        tmp = make_tmp(self)
        file = tmp / "x.txt"
        file.write_bytes(b"hello")
        self.assertEqual(renamers.file_digest(file, "crc32"), "3610a686")
        self.assertEqual(renamers.file_digest(file, "sha256")[:8], "2cf24dba")
        self.assertNotIn("shake_128", renamers.digest_algorithms())

    def test_plan_and_apply(self) -> None:
        tmp = make_tmp(self)
        file = tmp / "x.txt"
        file.write_text("content")
        self.assertIsNone(renamers.plan_rename(tmp / "abc.txt", "abc"))
        rename = renamers.plan_rename(file, "abc")
        assert rename is not None
        renamers.apply_rename(rename, overwrite=False)
        self.assertEqual((tmp / "abc.txt").read_text(), "content")


class ConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp(self)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.source = self.tmp / "photo.heic"
        self.source.write_bytes(b"heic")
        os.utime(self.source, (1_000_000, 1_000_000))
        (self.conversion,) = plan_conversions([self.source], ".jpg", remove_source=True)
        self.magick = write_executable(self.bin, "magick", FAKE_WRITER)
        self.exiftool = write_executable(self.bin, "exiftool", FAKE_WRITER)

    def convert(self, conversion: Conversion, overwrite: bool = False) -> None:
        convert_to_jpeg(
            conversion,
            ImageMagick(str(self.magick)),
            ExifTool(str(self.exiftool)),
            overwrite=overwrite,
        )

    def test_jpeg_conversion_keeps_timestamps_and_removes_source(self) -> None:
        self.convert(self.conversion)
        dest = self.tmp / "photo.jpg"
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.stat().st_mtime, 1_000_000)
        self.assertFalse(self.source.exists())
        self.assertEqual(recorded_argv(self.magick)[0], f"{self.source}[0]")
        exif_argv = recorded_argv(self.exiftool)
        self.assertIn("--Orientation", exif_argv)
        self.assertEqual(
            exif_argv[exif_argv.index("-tagsFromFile") + 1], str(self.source)
        )
        self.assertEqual(
            [p.name for p in self.tmp.iterdir() if p.name.startswith(".")], []
        )

    def test_existing_destination_is_refused(self) -> None:
        (self.tmp / "photo.jpg").write_text("old")
        with self.assertRaises(FileExistsError):
            self.convert(self.conversion)
        self.assertTrue(self.source.exists())
        self.assertFalse(recorded_argv_exists(self.magick))

    def test_same_extension_is_refused(self) -> None:
        jpg = self.tmp / "a.JPG"
        jpg.write_text("jpg")
        (conversion,) = plan_conversions([jpg], ".jpg", remove_source=False)
        with self.assertRaises(ValueError):
            self.convert(conversion)

    def test_mp4_remux_falls_back_to_aac(self) -> None:
        ffmpeg = write_executable(self.bin, "ffmpeg", FAKE_FFMPEG)
        ffprobe = write_executable(self.bin, "ffprobe", "print('1.0')")
        video = self.tmp / "clip.mkv"
        video.write_bytes(b"mkv")
        (conversion,) = plan_conversions([video], ".mp4", remove_source=False)
        os.environ["FAIL_COPY"] = "1"
        self.addCleanup(os.environ.pop, "FAIL_COPY")
        remux_to_mp4(
            conversion, FFMpegRunner(str(ffmpeg), str(ffprobe)), overwrite=False
        )
        calls = recorded_argv(ffmpeg)
        codecs = [call[call.index("-c:a") + 1] for call in calls]
        self.assertEqual(codecs, ["copy", "aac"])
        self.assertEqual((self.tmp / "clip.mp4").read_bytes(), b"mp4")
        self.assertTrue(video.exists())


def recorded_argv_exists(executable: Path) -> bool:
    return executable.with_suffix(".argv").exists()


@unittest.skipUnless(HAS_PILLOW, "needs the multitool extra (Pillow)")
class ImageHashTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.tmp = make_tmp(self)
        gradient = Image.linear_gradient("L").resize((64, 48)).convert("RGB")
        gradient.save(self.tmp / "a.png")
        gradient.save(self.tmp / "a_low.jpg", quality=30)
        gradient.rotate(180).save(self.tmp / "b.png")

    def test_near_duplicates_are_grouped(self) -> None:
        from multitool import imghash

        hasher = imghash.ImageHasher(16, cache=None)
        hashes = [(p, hasher.hash(p)) for p in sorted(self.tmp.iterdir())]
        self.assertEqual(len(hashes[0][1]), 64)
        groups = imghash.duplicate_groups(hashes, max_distance=8)
        self.assertEqual(groups, [[self.tmp / "a.png", self.tmp / "a_low.jpg"]])

    def test_groups_are_connected_components(self) -> None:
        from multitool import imghash

        hashes = [(Path("a"), "00"), (Path("b"), "03"), (Path("c"), "0f")]
        self.assertEqual(
            imghash.duplicate_groups(hashes, max_distance=2),
            [[Path("a"), Path("b"), Path("c")]],
        )
        self.assertEqual(imghash.duplicate_groups(hashes, max_distance=1), [])

    def test_cached_hash_is_reused(self) -> None:
        from multitool import imghash

        cache = UserCache(app="multitool", base_dir=self.tmp / "cache")
        self.addCleanup(cache.close)
        hasher = imghash.ImageHasher(16, cache)
        image = self.tmp / "a.png"
        computed = hasher.hash(image)
        cache.set(hasher._key(image), b"cafe")
        self.assertNotEqual(computed, "cafe")
        self.assertEqual(hasher.hash(image), "cafe")


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp(self)
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
        names = sorted(p.name for p in self.tmp.iterdir())
        self.assertIn(
            renamers.file_digest(self.tmp / names[0], "crc32") + ".txt", names
        )
        self.assertTrue(
            any(name.endswith(".dat") and name != "c.dat" for name in names)
        )

    def test_motionphotos_merge_keeps_video_unless_rm(self) -> None:
        (self.tmp / "a.jpg").write_bytes(JPEG)
        (self.tmp / "a.mp4").write_bytes(MP4)
        result = self.runner.invoke(cli, ["motionphotos", "merge", str(self.tmp)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            motionphotos.split((self.tmp / "a.jpg").read_bytes()), (JPEG, MP4)
        )
        self.assertTrue((self.tmp / "a.mp4").exists())

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


if __name__ == "__main__":
    unittest.main()
