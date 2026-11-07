# 0007. One user cache, keyed `<tool>/<digest>`

Status: accepted (2026-11-07)

## Context

`audio-grep` (transcripts), `img-hash` (image hashes) and `describe`
(descriptions) each need a cache. A cache per command means one directory,
expiry and size limit each, and nothing bounding the total.

## Decision

- One cache, `oddjob.core.cache.open_user_cache()`: a
  `foundation.cache.UserCache` in `$XDG_CACHE_HOME/oddjob`, owner-only.
  Entries expire after 180 days, and the least recently used are dropped once
  it passes 1 GiB. The size limit is checked at most once a day, by whichever
  command opens the cache first.
- Keys are `<tool>/<digest>` (`oddjob.lib.cache.cache_key`), so commands
  cannot collide. The digest covers a layout version, the input's content
  digest and everything else that changes the value. It never holds a path,
  so the cache cannot list which files were processed.
- Library code receives the store as a `ByteStore` Protocol and never opens
  it.
- What each command keys:
  - `audio-grep`: content, mtime, backend, model, language (0006);
  - `describe` and `img-embed-description`: content, prompt, backend and the
    backend's effective options (`Session.backend_options`) without
    `api_key`; the backend is built only on the first miss;
  - `img-hash` and `img-duplicates`: content and hash size.
- Commands that use it take `--no-cache`, except `audio-grep`.
- A command bumps its layout version when its value's format changes.

## Consequences

- One place to inspect or delete, with one expiry and one size limit.
- Every `img-hash` run reads each image to digest it instead of a `stat`,
  still much cheaper than decoding it. A moved or copied file hits.
- Backend defaults (e.g. a model default changed by an update) are not in
  `describe`'s key, since they are only known once the backend loads. Set
  `model` explicitly, or bump the layout version, to cut them off.
- `audio-grep` keys on the raw `--backend`/`--model`, not the effective
  options.

## Alternatives

- **A cache directory per command**: simple, but several expiries, size
  limits and places to delete.
- **Key `img-hash` by path, size and mtime**: no read of the file, but two
  files with the same size and mtime would share a hash, and a wrong hash
  silently breaks duplicate detection.
- **Evict only when the cache is opened after the expiry**: `UserCache`
  prunes once per expiry, so a size limit would be checked twice a year.
