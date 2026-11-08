"""Unit tests for the file commands' domain modules: media types, sidecars, motion
photos, renames and image hashes."""

import importlib.util
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from foundation.cache import UserCache

from oddjob.lib import (
    captions,
    cleanup,
    dates,
    media,
    motionphotos,
    renamers,
    sidecars,
)

if TYPE_CHECKING:
    import PIL.Image

HAS_PILLOW = importlib.util.find_spec("PIL") is not None

JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"
MP4 = b"\x00\x00\x00\x18ftypmp42fake-video"
SIDECAR_FILES = (Path("d/a.jpg"), Path("d/a.MP4"), Path("d/a.xmp"), Path("d/b.jpg"))


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
        self.assertTrue(media.is_autocrop_input(Path("logo.png")))
        self.assertFalse(media.is_autocrop_input(Path("logo.cropped.png")))
        self.assertFalse(media.is_autocrop_input(Path("notes.txt")))


class SidecarTests(unittest.TestCase):
    def test_groups_by_directory_and_stem(self) -> None:
        groups = sidecars.group_sidecars(SIDECAR_FILES)
        self.assertEqual([g.base for g in groups], [Path("d/a")])
        singles = sidecars.group_sidecars(SIDECAR_FILES, include_singles=True)
        self.assertEqual(len(singles), 2)

    def test_extension_filter_keeps_only_wanted_files(self) -> None:
        groups = sidecars.with_extensions(
            sidecars.group_sidecars(SIDECAR_FILES), ["jpg", ".mp4"]
        )
        self.assertEqual(groups[0].files, (Path("d/a.MP4"), Path("d/a.jpg")))
        strict = sidecars.with_extensions(
            sidecars.group_sidecars(SIDECAR_FILES), ["jpg", "mp4"], case_sensitive=True
        )
        self.assertEqual(strict, [])

    def test_sidecars_of(self) -> None:
        group = sidecars.sidecars_of(Path("d/a.jpg"), SIDECAR_FILES)
        self.assertIsNotNone(group)
        self.assertEqual(len(group.files), 3)  # type: ignore[union-attr]
        self.assertIsNone(sidecars.sidecars_of(Path("d/b.jpg"), SIDECAR_FILES))


class MotionPhotoTests(unittest.TestCase):
    def test_join_split_round_trip(self) -> None:
        joined = motionphotos.join(JPEG, MP4)
        self.assertEqual(motionphotos.split(joined), (JPEG, MP4))
        self.assertEqual(motionphotos.strip(joined), JPEG)

    def test_is_mp4_checks_the_major_brand(self) -> None:
        for brand in (b"isom", b"mp41", b"mp42", b"iso6", b"avc1"):
            with self.subTest(brand=brand):
                self.assertTrue(motionphotos.is_mp4(b"\x00\x00\x00\x18ftyp" + brand))
        for brand in (b"qt  ", b"heic", b"mif1", b"avif", b"3gp4"):
            with self.subTest(brand=brand):
                self.assertFalse(motionphotos.is_mp4(b"\x00\x00\x00\x18ftyp" + brand))

    def test_join_rejects_a_quicktime_video(self) -> None:
        mov = b"\x00\x00\x00\x14ftypqt  fake-video"
        with self.assertRaisesRegex(ValueError, "not an MP4"):
            motionphotos.join(JPEG, mov)

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
        file = make_tmp(self) / "x.txt"
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
        self.assertIsNotNone(rename)
        renamers.apply_rename(rename, overwrite=False)  # type: ignore[arg-type]
        self.assertEqual((tmp / "abc.txt").read_text(), "content")

    def test_fixed_extension(self) -> None:
        cases = {
            "d/IMG.JPEG": "d/IMG.jpg",
            "a.Jpg": "a.jpg",
            "clip.MPEG": "clip.mpg",
            "scan.tif": "scan.tiff",
            "x.tar.GZ": "x.tar.gz",
            "README": "README",
            ".bashrc": ".bashrc",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(renamers.fixed_extension(Path(source)), Path(expected))

    def test_plan_extension_fix(self) -> None:
        self.assertIsNone(renamers.plan_extension_fix(Path("a.jpg")))
        self.assertEqual(
            renamers.plan_extension_fix(Path("a.JPEG")),
            renamers.Rename(source=Path("a.JPEG"), destination=Path("a.jpg")),
        )


class CaptionPlanTests(unittest.TestCase):
    def test_images_without_sidecar_are_described(self) -> None:
        tmp = make_tmp(self)
        described, bare = tmp / "a.jpg", tmp / "b.png"
        (tmp / "a.description.txt").write_text("a cat", encoding="utf-8")
        planned = captions.plan_captions([described, bare], redescribe=False)
        self.assertEqual([caption.image for caption in planned], [described, bare])
        self.assertEqual([caption.generate for caption in planned], [False, True])
        self.assertEqual(planned[0].sidecar, tmp / "a.description.txt")
        self.assertEqual(planned[0].text(), "a cat")
        with self.assertRaises(FileNotFoundError):
            planned[1].text()

    def test_redescribe_describes_every_image(self) -> None:
        tmp = make_tmp(self)
        (tmp / "a.description.txt").write_text("a cat", encoding="utf-8")
        planned = captions.plan_captions([tmp / "a.jpg"], redescribe=True)
        self.assertTrue(planned[0].generate)

    def test_an_empty_description_is_an_error(self) -> None:
        tmp = make_tmp(self)
        (tmp / "a.description.txt").write_text(" \n", encoding="utf-8")
        caption = captions.Caption(tmp / "a.jpg", tmp / "a.description.txt")
        with self.assertRaisesRegex(ValueError, "empty description"):
            caption.text()


@unittest.skipUnless(HAS_PILLOW, "needs the images extra (Pillow)")
class ImageHashTests(unittest.TestCase):
    def setUp(self) -> None:
        from PIL import Image

        self.tmp = make_tmp(self)
        gradient = Image.linear_gradient("L").resize((64, 48)).convert("RGB")
        gradient.save(self.tmp / "a.png")
        gradient.save(self.tmp / "a_low.jpg", quality=30)
        gradient.rotate(180).save(self.tmp / "b.png")

    def test_near_duplicates_are_grouped(self) -> None:
        from oddjob.lib import imghash

        hasher = imghash.ImageHasher(16, cache=None)
        hashes = [(p, hasher.hash(p)) for p in sorted(self.tmp.iterdir())]
        self.assertEqual(len(hashes[0][1]), 64)
        groups = imghash.duplicate_groups(hashes, max_distance=8)
        self.assertEqual(groups, [[self.tmp / "a.png", self.tmp / "a_low.jpg"]])

    def test_groups_are_connected_components(self) -> None:
        from oddjob.lib import imghash

        hashes = [(Path("a"), "00"), (Path("b"), "03"), (Path("c"), "0f")]
        self.assertEqual(
            imghash.duplicate_groups(hashes, max_distance=2),
            [[Path("a"), Path("b"), Path("c")]],
        )
        self.assertEqual(imghash.duplicate_groups(hashes, max_distance=1), [])

    def test_hashes_are_cached_by_content_not_path(self) -> None:
        from oddjob.lib import imghash

        cache = UserCache(app="oddjob", base_dir=self.tmp / "cache")
        self.addCleanup(cache.close)
        hasher = imghash.ImageHasher(16, cache)
        image = self.tmp / "a.png"
        first = hasher.hash(image)
        (self.tmp / "copy.png").write_bytes(image.read_bytes())
        self.assertEqual(hasher.hash(self.tmp / "copy.png"), first)
        (key,) = cache.iter()
        self.assertRegex(key, r"^img-hash/[0-9a-f]{64}$")
        hasher.hash(self.tmp / "b.png")
        imghash.ImageHasher(8, cache).hash(image)
        self.assertEqual(len(list(cache.iter())), 3)

    def test_decode_problem(self) -> None:
        from oddjob.lib import imghash

        whole = self.tmp / "a.jpg"
        (self.tmp / "a_low.jpg").rename(whole)
        truncated = self.tmp / "truncated.jpg"
        truncated.write_bytes(whole.read_bytes()[: whole.stat().st_size // 2])
        garbage = self.tmp / "garbage.png"
        garbage.write_bytes(b"not an image")
        self.assertIsNone(imghash.decode_problem(whole))
        self.assertIsNone(imghash.decode_problem(self.tmp / "a.png"))
        self.assertIn("truncated", (imghash.decode_problem(truncated) or "").lower())
        self.assertIn("cannot identify", imghash.decode_problem(garbage) or "")

    def test_an_unreadable_file_is_not_a_decode_problem(self) -> None:
        from oddjob.lib import imghash

        with self.assertRaises(FileNotFoundError):
            imghash.decode_problem(self.tmp / "missing.png")


@unittest.skipUnless(HAS_PILLOW, "needs the images extra (Pillow)")
class ImageEditTests(unittest.TestCase):
    @staticmethod
    def encoded(image: "PIL.Image.Image", image_format: str, **params: object) -> bytes:
        from io import BytesIO

        output = BytesIO()
        image.save(output, format=image_format, **params)
        return output.getvalue()

    def test_autocrop_keeps_only_the_opaque_box_format_and_exif(self) -> None:
        from io import BytesIO

        from PIL import Image

        from oddjob.lib import imgedit

        image = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
        image.paste((255, 0, 0, 255), (5, 10, 15, 25))
        exif = Image.Exif()
        exif[0x010E] = "a description"  # ImageDescription
        content = self.encoded(image, "PNG", exif=exif)
        with Image.open(BytesIO(imgedit.autocrop(content))) as cropped:
            self.assertEqual((cropped.format, cropped.size), ("PNG", (10, 15)))
            self.assertEqual(cropped.getexif()[0x010E], "a description")

    def test_autocrop_needs_transparent_and_visible_pixels(self) -> None:
        from PIL import Image

        from oddjob.lib import imgedit

        opaque = self.encoded(Image.new("RGB", (4, 4)), "PNG")
        empty = self.encoded(Image.new("RGBA", (4, 4), (0, 0, 0, 0)), "PNG")
        with self.assertRaisesRegex(ValueError, "no transparency"):
            imgedit.autocrop(opaque)
        with self.assertRaisesRegex(ValueError, "fully transparent"):
            imgedit.autocrop(empty)

    def test_reduced_size_keeps_the_aspect_ratio(self) -> None:
        from oddjob.lib import imgedit

        self.assertEqual(imgedit.reduced_size((4000, 3000), 2160), (2160, 1620))
        self.assertEqual(imgedit.reduced_size((3000, 4000), 2160), (1620, 2160))
        self.assertEqual(imgedit.reduced_size((5000, 1), 10), (10, 1))
        self.assertIsNone(imgedit.reduced_size((2160, 100), 2160))

    def test_reduce_keeps_format_and_exif(self) -> None:
        from io import BytesIO

        from PIL import Image

        from oddjob.lib import imgedit

        exif = Image.Exif()
        exif[0x010E] = "a description"  # ImageDescription
        content = self.encoded(Image.new("RGB", (30, 60)), "JPEG", exif=exif)
        with Image.open(BytesIO(imgedit.reduce(content, 20))) as reduced:
            self.assertEqual((reduced.format, reduced.size), ("JPEG", (10, 20)))
            self.assertEqual(reduced.getexif()[0x010E], "a description")

    def test_reduce_refuses_animations_and_images_that_fit(self) -> None:
        from PIL import Image

        from oddjob.lib import imgedit

        frames = [Image.new("RGB", (40, 40), color) for color in ("red", "blue")]
        animated = self.encoded(
            frames[0], "WEBP", save_all=True, append_images=frames[1:]
        )
        with self.assertRaisesRegex(ValueError, "animated"):
            imgedit.reduce(animated, 10)
        with self.assertRaisesRegex(ValueError, "already fits"):
            imgedit.reduce(self.encoded(frames[0], "PNG"), 40)


class DateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.when = datetime(2019, 7, 14, 18, 3, 22).astimezone()

    def test_name_pattern_reads_dates_from_names(self) -> None:
        default = dates.name_pattern(dates.DEFAULT_NAME_FORMAT)
        android = dates.name_pattern("IMG_%Y%m%d_%H%M%S")
        short = dates.name_pattern("%d.%m.%y")
        for name, pattern, expected in (
            ("2019-07-14 18.03.22 9f3a01bc.jpg", default, self.when),
            ("IMG_20190714_180322.jpg", android, self.when),
            ("trip 14.07.19.jpg", short, self.when.replace(hour=0, minute=0, second=0)),
        ):
            self.assertEqual(dates.date_from_name(name, pattern), expected, name)
        with self.assertRaises(dates.DateNotFoundError):
            dates.date_from_name("IMG_1234.jpg", default)

    def test_name_pattern_rejects_bad_formats(self) -> None:
        for name_format in ("%Y-%q", "%Y %Y-%m-%d", "%H.%M"):
            with self.assertRaises(ValueError, msg=name_format):
                dates.name_pattern(name_format)

    def test_recorded_offsets_resolve_the_repeated_hour(self) -> None:
        previous = os.environ.get("TZ")
        self.addCleanup(self._restore_timezone, previous)
        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        wall = "2019:10:27 02:30:00"

        first = dates.date_from_tags(
            {"DateTimeOriginal": wall, "OffsetTimeOriginal": "+02:00"}
        )
        second = dates.date_from_tags(
            {"DateTimeOriginal": wall, "OffsetTimeOriginal": "+01:00"}
        )
        quicktime = dates.date_from_tags(
            {"MediaCreateDate": f"{wall}+0100"}, utc_based=True
        )

        self.assertEqual(second - first, timedelta(hours=1))
        self.assertEqual(quicktime, second)
        self.assertEqual(
            dates.date_from_tags(
                {"DateTimeOriginal": wall, "OffsetTimeOriginal": "garbage"}
            ),
            first,
        )

    def test_ambiguous_local_time_takes_the_first_occurrence(self) -> None:
        previous = os.environ.get("TZ")
        self.addCleanup(self._restore_timezone, previous)
        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()

        repeated = dates.local_time("2019:10:27 02:30:00")

        self.assertEqual(repeated.utcoffset(), timedelta(hours=2))

    @staticmethod
    def _restore_timezone(previous: str | None) -> None:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

    def test_date_from_tags_prefers_the_original_and_skips_zeroes(self) -> None:
        tags = {
            "DateTimeOriginal": "0000:00:00 00:00:00",
            "CreateDate": "2019:07:14 18:03:22",
            "MediaCreateDate": "2001:01:01 00:00:00",
        }
        self.assertEqual(dates.date_from_tags(tags), self.when)
        tags["DateTimeOriginal"] = "2018:01:02 03:04:05"
        self.assertEqual(dates.date_from_tags(tags).year, 2018)
        self.assertIsNone(dates.date_from_tags({}))

    def test_dated_name_normalizes_the_extension(self) -> None:
        self.assertEqual(
            dates.dated_name(Path("d/IMG_1.JPEG"), self.when, "9f3a01bc"),
            Path("d/2019-07-14 18.03.22 9f3a01bc.jpg"),
        )


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp(self)

    def touch(self, relative: str, mode: int = 0o644) -> Path:
        path = self.tmp / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        path.chmod(mode)
        return path

    def test_junk_names(self) -> None:
        for name in (".DS_Store", "Icon\r", ".directory", "Thumbs.db", "DESKTOP.INI"):
            self.assertTrue(cleanup.is_junk_file(Path(name)), name)
        for name in ("ds_store", "photo.jpg", "._", ".Trash"):
            self.assertFalse(cleanup.is_junk_file(Path(name)), name)
        for name in (".Trashes", "$RECYCLE.BIN", ".Trash-1000"):
            self.assertTrue(cleanup.is_junk_directory(Path(name)), name)
        self.assertFalse(cleanup.is_junk_directory(Path(".Trash-x")))

    def test_apple_double_only_next_to_its_file(self) -> None:
        self.touch("a.jpg")
        self.assertTrue(cleanup.is_junk_file(self.touch("._a.jpg")))
        self.assertFalse(cleanup.is_junk_file(self.touch("._orphan.jpg")))

    def test_plan_removes_junk_without_descending_into_junk_dirs(self) -> None:
        self.touch("d/.DS_Store")
        self.touch("d/a.jpg")
        self.touch(".Trashes/501/old.jpg")
        planned = cleanup.plan_cleanup([self.tmp], fix_permissions=False)
        self.assertEqual(
            [action.describe() for action in planned],
            [f"rm -r {self.tmp / '.Trashes'}", f"rm {self.tmp / 'd/.DS_Store'}"],
        )

    def test_perms_planned_only_when_asked_and_different(self) -> None:
        script = self.touch("d/run.sh", 0o755)
        self.touch("d/ok.jpg")
        (self.tmp / "d").chmod(0o700)
        self.assertEqual(cleanup.plan_cleanup([self.tmp], fix_permissions=False), [])
        planned = cleanup.plan_cleanup([self.tmp / "d"], fix_permissions=True)
        self.assertEqual(
            planned,
            [
                cleanup.Chmod(path=self.tmp / "d", mode=0o755),
                cleanup.Chmod(path=script, mode=0o644),
            ],
        )

    def test_symlinks_are_left_alone(self) -> None:
        target = self.touch("real/.DS_Store", 0o600)
        (self.tmp / "link").symlink_to(self.tmp / "real")
        (self.tmp / "real" / "Thumbs.db").symlink_to(target)
        planned = cleanup.plan_cleanup([self.tmp / "link"], fix_permissions=True)
        self.assertEqual(planned, [])
        planned = cleanup.plan_cleanup([self.tmp / "real"], fix_permissions=False)
        self.assertEqual(planned, [cleanup.Removal(path=target, directory=False)])


if __name__ == "__main__":
    unittest.main()
