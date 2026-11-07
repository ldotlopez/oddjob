"""The shared user cache: location, expiry and the size limit."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from foundation.cache import MissingKeyError, SizeEvictionPolicy

from glados.core.cache import CACHE_MAX_BYTES, open_user_cache


class UserCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.tmp)})
        )

    def test_lives_in_the_glados_cache_directory_and_is_limited_to_1_gib(self) -> None:
        with open_user_cache() as cache:
            cache.set("tool/key", b"value")
            self.assertEqual(cache.get("tool/key"), b"value")
            policy = cache.eviction_policy
        self.assertTrue((self.tmp / "glados" / "entries").is_dir())
        self.assertIsInstance(policy, SizeEvictionPolicy)
        self.assertEqual(CACHE_MAX_BYTES, 1024**3)

    def test_pruning_drops_the_least_recently_used_entries_over_the_limit(self) -> None:
        with open_user_cache() as cache:
            cache.eviction_policy = SizeEvictionPolicy(25)
            for name in ("old", "middle", "new"):
                cache.set(f"tool/{name}", b"x" * 10)
                cache.get(f"tool/{name}")
            report = cache.prune()
            self.assertEqual(len(report.removed), 1)
            with self.assertRaises(MissingKeyError):
                cache.get("tool/old")
            self.assertEqual(cache.get("tool/new"), b"x" * 10)


if __name__ == "__main__":
    unittest.main()
