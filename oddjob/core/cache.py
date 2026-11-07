"""The user cache shared by every oddjob command (see oddjob/lib/cache.py for
its keys): `$XDG_CACHE_HOME/oddjob`, owner-only. An entry expires after
CACHE_EXPIRATION, and the least recently used entries are dropped when the
cache outgrows CACHE_MAX_BYTES."""

from __future__ import annotations

from foundation.cache import SizeEvictionPolicy, UserCache

CACHE_APP = "oddjob"
CACHE_EXPIRATION = 180 * 24 * 60 * 60  # seconds
CACHE_MAX_BYTES = 1024**3  # 1 GiB
# The size limit is enforced at most this often, by whichever command opens
# the cache first, so the cache can exceed it for up to this long.
SIZE_CHECK_INTERVAL = 24 * 60 * 60  # seconds


def open_user_cache() -> UserCache:
    """The shared cache; close it (or use it as a context manager) when done."""
    cache = UserCache(app=CACHE_APP, expiration_time=CACHE_EXPIRATION)
    cache.eviction_policy = SizeEvictionPolicy(CACHE_MAX_BYTES)
    if cache.storage.claim_maintenance(SIZE_CHECK_INTERVAL):
        cache.prune()
    return cache
