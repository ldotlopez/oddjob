"""oddjob's file commands against the real ImageMagick, exiftool and ffmpeg.

Each class skips when a tool it needs is not on PATH; img-duplicates also
needs the images extra (Pillow)."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner, Result

from oddjob.cli import cli
from oddjob.lib import motionphotos

HAS_PILLOW = importlib.util.find_spec("PIL") is not None


def missing(*alternatives: str) -> bool:
    """Whether none of `alternatives` is on PATH."""
    return all(shutil.which(name) is None for name in alternatives)


def run_tool(*args: str | Path) -> str:
    """Run a fixture-building or checking tool; return its stdout."""
    proc = subprocess.run(
        [str(arg) for arg in args], capture_output=True, text=True, check=True
    )
    return proc.stdout


def magick(*args: str | Path) -> None:
    run_tool("magick" if shutil.which("magick") else "convert", *args)


def exif_tag(path: Path, tag: str) -> str:
    """One tag's value, numeric (`-n`), empty if absent."""
    return run_tool("exiftool", "-s3", "-n", f"-{tag}", path).strip()


def make_video(path: Path, seconds: int = 1) -> None:
    """A short test pattern with a sine tone, in `path`'s container."""
    run_tool(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=64x48:rate=10",
        "-f", "lavfi", "-i", f"sine=duration={seconds}",
        "-c:v", "mpeg4", "-shortest", path,
    )  # fmt: skip


def stream_codecs(path: Path) -> list[str]:
    output = run_tool(
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
        "-of", "csv=p=0", path,
    )  # fmt: skip
    return output.split()


class IntegrationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runner = CliRunner()

    def oddjob(self, *args: str | Path) -> Result:
        result = self.runner.invoke(cli, [str(arg) for arg in args])
        self.assertEqual(result.exit_code, 0, result.output)
        return result


@unittest.skipIf(
    missing("magick", "convert") or missing("exiftool"),
    "needs ImageMagick and exiftool",
)
class JpgizeIntegrationTest(IntegrationCase):
    def test_keeps_tags_and_uprights_the_image(self) -> None:
        source = self.tmp / "photo.png"
        magick("-size", "40x20", "gradient:red-blue", source)
        run_tool(
            "exiftool", "-q", "-overwrite_original",
            "-PNG:Artist=Tester", "-EXIF:Orientation#=6", source,
        )  # fmt: skip
        self.oddjob("jpgize", "--rm", self.tmp)
        converted = self.tmp / "photo.jpg"
        self.assertFalse(source.exists())
        self.assertEqual(exif_tag(converted, "IFD0:Artist"), "Tester")
        self.assertEqual(exif_tag(converted, "ImageSize"), "20 40")
        self.assertIn(exif_tag(converted, "Orientation"), ("", "1"))


@unittest.skipIf(missing("ffmpeg") or missing("ffprobe"), "needs ffmpeg and ffprobe")
class Mp4izeIntegrationTest(IntegrationCase):
    def test_remuxes_without_reencoding_video(self) -> None:
        source = self.tmp / "clip.mkv"
        make_video(source)
        self.oddjob("mp4ize", source)
        remuxed = self.tmp / "clip.mp4"
        self.assertTrue(source.exists())
        self.assertEqual(stream_codecs(remuxed)[0], "mpeg4")
        self.assertIn(
            "mp4", run_tool("ffprobe", "-v", "error", "-show_format", remuxed)
        )


@unittest.skipIf(
    missing("magick", "convert") or missing("ffmpeg") or missing("ffprobe"),
    "needs ImageMagick and ffmpeg",
)
class MotionPhotoIntegrationTest(IntegrationCase):
    def test_join_and_split_round_trip(self) -> None:
        still, clip = self.tmp / "still.jpg", self.tmp / "clip.mp4"
        magick("-size", "64x48", "gradient:red-blue", still)
        make_video(clip)
        joined = self.tmp / "motion.jpg"
        self.oddjob("motionphotos", "join", "-i", still, "--video", clip, "-o", joined)
        self.oddjob("motionphotos", "check", joined)
        magick(joined, self.tmp / "decoded.png")  # still a readable JPEG

        image, video = self.tmp / "out.jpg", self.tmp / "out.mp4"
        self.oddjob("motionphotos", "split", joined, "-i", image, "--video", video)
        self.assertEqual(image.read_bytes(), still.read_bytes())
        self.assertEqual(video.read_bytes(), clip.read_bytes())
        self.assertEqual(stream_codecs(video), stream_codecs(clip))

        self.oddjob("motionphotos", "strip", "-y", joined)
        self.assertIsNone(motionphotos.MotionPhoto.parse(joined.read_bytes()).video)


@unittest.skipUnless(HAS_PILLOW, "needs the images extra (Pillow)")
@unittest.skipIf(missing("magick", "convert"), "needs ImageMagick")
class ImgDuplicatesIntegrationTest(IntegrationCase):
    def test_groups_a_reencoded_copy(self) -> None:
        original = self.tmp / "a.png"
        magick("-size", "64x48", "gradient:red-blue", original)
        magick(original, "-quality", "40", self.tmp / "a_copy.jpg")
        magick(
            "-size", "64x48", "gradient:red-blue", "-rotate", "180", self.tmp / "b.png"
        )
        result = self.oddjob("img-duplicates", "--no-cache", self.tmp)
        groups = result.output.split("group ")[1:]
        self.assertEqual(len(groups), 1, result.output)
        self.assertIn(str(original), groups[0])
        self.assertIn(str(self.tmp / "a_copy.jpg"), groups[0])
        self.assertNotIn(str(self.tmp / "b.png"), groups[0])


@unittest.skipIf(
    missing("magick", "convert") or missing("exiftool"),
    "needs ImageMagick and exiftool",
)
class ImgCaptionIntegrationTest(IntegrationCase):
    def test_sets_xmp_and_exif_descriptions(self) -> None:
        image = self.tmp / "a.jpg"
        magick("-size", "16x16", "xc:red", image)
        (self.tmp / "a.description.txt").write_text("Un gato, señor", encoding="utf-8")
        self.oddjob("img-embed-description", "-y", self.tmp)
        self.assertEqual(exif_tag(image, "XMP-dc:Description"), "Un gato, señor")
        self.assertEqual(exif_tag(image, "EXIF:ImageDescription"), "Un gato, señor")


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(
    missing("magick", "convert") or missing("exiftool") or missing("ffmpeg"),
    "needs ImageMagick, exiftool and ffmpeg",
)
class DateSyncIntegrationTest(IntegrationCase):
    def test_name_to_exif_and_back_for_an_image_and_a_video(self) -> None:
        stem = "2019-07-14 18.03.22 00000000"
        image, video = self.tmp / f"{stem}.jpg", self.tmp / f"{stem}.mp4"
        magick("-size", "64x48", "gradient:red-blue", image)
        make_video(video)
        self.oddjob("date-copy", "--from", "name", "--to", "exif", "-y", self.tmp)
        self.assertEqual(exif_tag(image, "DateTimeOriginal"), "2019:07:14 18:03:22")
        # QuickTime stores UTC: written and read back as local time.
        local = run_tool(
            "exiftool", "-s3", "-api", "QuickTimeUTC", "-d", "%Y:%m:%d %H:%M:%S",
            "-MediaCreateDate", video,
        )  # fmt: skip
        self.assertEqual(local.strip(), "2019:07:14 18:03:22")

        self.oddjob("date-copy", "--from", "exif", "--to", "name", self.tmp)
        names = sorted(path.name for path in self.tmp.iterdir())
        self.assertEqual(len(names), 2)
        for name in names:
            self.assertTrue(name.startswith("2019-07-14 18.03.22 "), name)
            self.assertNotIn("00000000", name)


@unittest.skipIf(
    missing("magick", "convert") or missing("exiftool") or missing("ffmpeg"),
    "needs ImageMagick, exiftool and ffmpeg",
)
class DateSyncRepeatedHourIntegrationTest(IntegrationCase):
    """02:30 happens twice when daylight saving ends: the recorded offset
    says which one, both on reading and on writing."""

    SECOND_PASS = datetime(2019, 10, 27, 1, 30, tzinfo=UTC)  # 02:30 at +01:00

    def setUp(self) -> None:
        super().setUp()
        previous = os.environ.get("TZ")
        self.addCleanup(self.restore_timezone, previous)
        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()

    @staticmethod
    def restore_timezone(previous: str | None) -> None:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

    def test_reads_the_recorded_offset(self) -> None:
        image, video = self.tmp / "a.jpg", self.tmp / "b.mp4"
        magick("-size", "16x16", "xc:red", image)
        make_video(video)
        run_tool(
            "exiftool", "-q", "-overwrite_original",
            "-DateTimeOriginal=2019:10:27 02:30:00", "-OffsetTimeOriginal=+01:00",
            image,
        )  # fmt: skip
        run_tool(
            "exiftool", "-q", "-overwrite_original", "-api", "QuickTimeUTC",
            "-CreateDate=2019:10:27 02:30:00+01:00", video,
        )  # fmt: skip

        self.oddjob("date-copy", "--from", "exif", "--to", "mtime", self.tmp)

        for path in (image, video):
            self.assertEqual(path.stat().st_mtime, self.SECOND_PASS.timestamp(), path)

    def test_writes_the_offset(self) -> None:
        image, video = self.tmp / "a.jpg", self.tmp / "b.mp4"
        magick("-size", "16x16", "xc:red", image)
        make_video(video)
        for path in (image, video):
            os.utime(path, (0, self.SECOND_PASS.timestamp()))

        self.oddjob("date-copy", "--from", "mtime", "--to", "exif", "-y", self.tmp)

        self.assertEqual(exif_tag(image, "OffsetTimeOriginal"), "+01:00")
        self.assertEqual(exif_tag(image, "DateTimeOriginal"), "2019:10:27 02:30:00")
        local = run_tool(
            "exiftool", "-s3", "-api", "QuickTimeUTC", "-d", "%Y:%m:%d %H:%M:%S%z",
            "-MediaCreateDate", video,
        )  # fmt: skip
        self.assertEqual(local.strip(), "2019:10:27 02:30:00+0100")


@unittest.skipIf(
    missing("magick", "convert") or missing("exiftool"),
    "needs ImageMagick and exiftool",
)
class PhotoLintIntegrationTest(IntegrationCase):
    def test_set_zone_fixes_what_check_finds(self) -> None:
        image = self.tmp / "a.jpg"
        magick("-size", "16x16", "xc:red", image)
        run_tool(
            "exiftool", "-q", "-overwrite_original",
            "-DateTimeOriginal=2019:07:14 18:03:22",
            "-ModifyDate=2019:12:01 10:00:00", image,
        )  # fmt: skip
        found = self.runner.invoke(cli, ["photo-lint", "check", str(self.tmp)])
        self.assertEqual((found.exit_code, found.stdout), (1, f"{image}: no-zone\n"))

        set_zone = ("photo-lint", "set-zone", "--zone", "Europe/Madrid", self.tmp)
        self.oddjob(*set_zone)

        fixed = self.tmp / "a.fixed.jpg"
        self.assertEqual(exif_tag(fixed, "OffsetTimeOriginal"), "+02:00")
        self.assertEqual(exif_tag(fixed, "OffsetTime"), "+01:00")
        self.assertEqual(exif_tag(fixed, "DateTimeOriginal"), "2019:07:14 18:03:22")
        self.assertEqual(exif_tag(image, "OffsetTimeOriginal"), "")

        fixed.unlink()
        self.oddjob(*set_zone, "--in-place")
        self.assertEqual(exif_tag(image, "OffsetTimeOriginal"), "+02:00")
        self.assertEqual(self.oddjob("photo-lint", "check", self.tmp).stdout, "")
