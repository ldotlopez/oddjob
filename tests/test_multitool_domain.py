"""Unit tests for multitool's domain modules: media types, sidecars, motion
photos, renames and image hashes."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from foundation.cache import UserCache

from multitool import media, motionphotos, renamers, sidecars

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

    def test_unchanged_file_is_answered_from_the_cache(self) -> None:
        from multitool import imghash

        cache = UserCache(app="multitool", base_dir=self.tmp / "cache")
        self.addCleanup(cache.close)
        hasher = imghash.ImageHasher(16, cache)
        image = self.tmp / "a.png"
        first = hasher.hash(image)
        # Same size and mtime but unreadable content: only the cache can answer.
        stat = image.stat()
        image.write_bytes(b"\0" * stat.st_size)
        os.utime(image, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(hasher.hash(image), first)
        with self.assertRaises(OSError):
            imghash.ImageHasher(16, cache=None).hash(image)


if __name__ == "__main__":
    unittest.main()
