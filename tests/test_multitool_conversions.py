"""Unit tests for multitool's conversion steps, run as Jobs against fake
ImageMagick, exiftool and ffmpeg executables."""

import os
import tempfile
import unittest
from pathlib import Path

from support import NullReporter, recorded_argv, write_executable

from filejobs.pipeline import Job
from filejobs.runners import FFMpegRunner
from multitool.captions import CaptionStep
from multitool.conversions import (
    JpegConversionStep,
    Mp4RemuxStep,
    plan_conversions,
    run_conversion,
)
from multitool.external import ExifTool, ImageMagick

# Records its argv, then writes the last argument as an output file.
FAKE_WRITER = """\
import json, sys
from pathlib import Path
Path(__file__).with_suffix(".argv").write_text(json.dumps(sys.argv[1:]))
Path(sys.argv[-1]).write_bytes(b"converted")
"""

# Records each call's argv; fails on an audio stream copy when FAIL_COPY is set.
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
print("out_time=00:00:00.500000")
print("progress=end")
"""


class ConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.source = self.tmp / "photo.heic"
        self.source.write_bytes(b"heic")
        os.utime(self.source, (1_000_000, 1_000_000))
        self.magick = write_executable(self.bin, "magick", FAKE_WRITER)
        self.exiftool = write_executable(self.bin, "exiftool", FAKE_WRITER)
        self.step = JpegConversionStep(
            ImageMagick(str(self.magick)), ExifTool(str(self.exiftool))
        )

    def convert(
        self, source: Path, remove_source: bool, overwrite: bool = False
    ) -> None:
        (conversion,) = plan_conversions([source], "jpg", remove_source)
        run_conversion(conversion, self.step, NullReporter(), overwrite=overwrite)

    def test_jpeg_conversion_keeps_timestamps_and_removes_source(self) -> None:
        self.convert(self.source, remove_source=True)
        dest = self.tmp / "photo.jpg"
        self.assertEqual(dest.read_bytes(), b"converted")
        self.assertEqual(dest.stat().st_mtime, 1_000_000)
        self.assertFalse(self.source.exists())
        self.assertEqual(recorded_argv(self.magick)[0], f"{self.source}[0]")
        exif_argv = recorded_argv(self.exiftool)
        self.assertIn("--Orientation", exif_argv)
        self.assertEqual(
            exif_argv[exif_argv.index("-tagsFromFile") + 1], str(self.source)
        )

    def test_existing_destination_is_refused_before_converting(self) -> None:
        (self.tmp / "photo.jpg").write_text("old")
        with self.assertRaises(FileExistsError):
            self.convert(self.source, remove_source=True)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.magick.with_suffix(".argv").exists())

    def test_same_extension_is_refused(self) -> None:
        jpg = self.tmp / "a.JPG"
        jpg.write_text("jpg")
        with self.assertRaises(ValueError):
            self.convert(jpg, remove_source=False, overwrite=True)
        self.assertEqual(jpg.read_text(), "jpg")

    def test_mp4_remux_falls_back_to_aac_and_reports_progress(self) -> None:
        ffmpeg = write_executable(self.bin, "ffmpeg", FAKE_FFMPEG)
        ffprobe = write_executable(self.bin, "ffprobe", "print('1.0')")
        video = self.tmp / "clip.mkv"
        video.write_bytes(b"mkv")
        os.environ["FAIL_COPY"] = "1"
        self.addCleanup(os.environ.pop, "FAIL_COPY")
        step = Mp4RemuxStep(FFMpegRunner(str(ffmpeg), str(ffprobe)))
        events = list(step.run(video))
        self.assertEqual(events[-1].total, 1.0)
        self.assertTrue(any(not e.done and e.completed == 0.5 for e in events))
        produced = events[-1].result
        self.addCleanup(produced.unlink, missing_ok=True)
        self.assertEqual(produced.read_bytes(), b"mp4")
        codecs = [call[call.index("-c:a") + 1] for call in recorded_argv(ffmpeg)]
        self.assertEqual(codecs, ["copy", "aac"])


class CaptionStepTests(unittest.TestCase):
    def test_writes_tags_into_a_copy_and_lands_in_place(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        exiftool = write_executable(tmp, "exiftool", FAKE_WRITER)
        image = tmp / "a.jpg"
        image.write_bytes(b"jpeg")
        os.utime(image, (1_000_000, 1_000_000))
        job = Job(
            steps=[(CaptionStep(ExifTool(str(exiftool)), "un gato"), "Captioning")],
            dest_fn=lambda _image: image,
        )
        with self.assertRaises(FileExistsError):
            job.run(image, NullReporter())
        self.assertEqual(image.read_bytes(), b"jpeg")

        job.run(image, NullReporter(), overwrite=True)

        argv = recorded_argv(exiftool)
        self.assertEqual(
            argv[:-1],
            [
                "-quiet", "-overwrite_original", "-charset", "exif=utf8",
                "-XMP-dc:Description=un gato", "-EXIF:ImageDescription=un gato",
            ],
        )  # fmt: skip
        self.assertNotEqual(Path(argv[-1]), image)
        self.assertEqual(image.read_bytes(), b"converted")
        self.assertEqual(image.stat().st_mtime, 1_000_000)


if __name__ == "__main__":
    unittest.main()
