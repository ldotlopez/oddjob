# 0012. One user cache, keyed `<tool>/<digest>`

Status: accepted (2026-11-07). Partly supersedes 0009 (cache location and key).

## Context

0009 gave audio-grep a cache of its own in `$XDG_CACHE_HOME/glados/transcripts`
(180-day expiry), and `img-hash` had another in `.../imghash` (30 days, keyed
by path, size and mtime). `describe` needs a third, and each cache opened its
own directory with its own expiry and no size limit.

## Decision

- One cache, `glados.core.cache.open_user_cache()`: a `foundation.cache.UserCache`
  in `$XDG_CACHE_HOME/glados`, owner-only, entries expiring after 180 days, the
  least recently used dropped when it passes 1 GiB. The size limit is checked at
  most once a day, by whichever command opens the cache first.
- Keys are `<tool>/<digest>` (`glados.lib.cache.cache_key`), so commands
  cannot collide. The digest covers a layout version, the content digest of the
  input file and everything else that changes the value; it holds no path, so
  the cache cannot list which files were processed. Library code receives the
  store as a `ByteStore` Protocol and never opens it.
- `audio-grep` (content, mtime, backend, model, language), `describe` (content,
  prompt, backend, the backend's effective options without `api_key`; no
  mtime) and `img-hash` (content, hash size) use it. `describe` and the hash
  commands take `--no-cache`.
- `describe` resolves the backend name and options without loading the backend
  (`Glados.backend_options`), and builds the backend only on the first miss.

## Consequences

- The old `transcripts` and `imghash` directories are no longer read. Each
  transcript and hash is computed once more and the old directories can be
  deleted.
- Every `img-hash` run reads each image once to digest it, in place of a
  `stat`, still much cheaper than decoding it. A moved or copied file hits.
- One expiry for all: hashes now live 180 days, which is harmless because their
  keys change with the content.
- Backend defaults (e.g. a model default changed by a glados update) are not
  in `describe`'s key, since they are only known once the backend is loaded.
  Set `model` explicitly, or bump the layout version, to cut them off.
- `audio-grep` still keys on the raw `--backend`/`--model` rather than the
  effective options.

## Alternatives

- **A cache directory per command**: simple, but three expiries, three
  size limits and three places to delete.
- **Key `img-hash` by path, size and mtime**: no read of the file, but two
  different files with the same size and mtime would share a hash, and a
  wrong hash silently breaks duplicate detection.
- **Evict only when opened after the 180-day expiry**: `UserCache` prunes once
  per expiry, so a size limit would be checked twice a year.
