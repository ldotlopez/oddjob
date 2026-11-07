# 0009. audio-grep: one glados command with a transcript cache, replacing srt-grep

Status: accepted (2026-11-07), partly superseded by 0012 (the cache location and key). Partly supersedes 0008 (its `agrep` split).

## Context

0008 split ocdutils' `agrep` along the model boundary: `glados transcribe
-f srt` wrote a sidecar, and `multitool srt-grep` searched it. In use the
split was unnatural. Searching what was said in a set of recordings took two
commands, left an `.srt` next to every file whether or not it was wanted,
and `srt-grep` only did a case-insensitive substring match instead of
grep's options.

## Decision

- `agrep` becomes the single glados command `audio-grep`, under 0008's own
  rule for mixed tools: "If the split is unnatural, the whole tool is a
  glados task." It reuses the `transcribe` backends (no entry-point group
  of its own) and is also a standalone script.
- `multitool srt-grep` and `multitool/subtitles.py` are removed. Plain
  `grep` already covers existing sidecars.
- It runs the system `grep`. Arguments that are existing directories or
  audio/video files are the inputs, and everything else goes to grep
  unchanged, so grep's option grammar (GNU grep, ugrep, ...) is never
  parsed here. Its own options are long-only. Each transcript is written to
  a temporary file, grep runs once over all of them, and the temporary paths
  in its output are replaced by the media paths. The exit status is grep's,
  or 2 if an input could not be transcribed.
- No sidecar is written. Transcripts (segments, so any `--transcript-format`
  can be rendered from them) are cached through `foundation.cache.UserCache`
  in `$XDG_CACHE_HOME/glados/transcripts`, owner-only, with a 180-day TTL.
- The cache key is `sha256(content sha256, mtime_ns, --backend, --model,
  --language)`. It holds no path, so the cache cannot be used to find out
  which files were transcribed. A changed file, or different settings, is a
  miss.
- The grep subprocess is an adapter in `glados/tasks/grep.py`, not in
  `filejobs`: only glados uses it (0008, rule 4).

## Consequences

- One command searches recordings directly, with every grep option, and the
  second search of a file costs a checksum instead of a transcription.
- The backend loads only on a cache miss.
- The transcript text itself is stored in the user cache. Nothing outside
  that directory is written.
- `--backend`/`--model` are keyed as given, so the same model named two ways
  (default vs. explicit) is transcribed twice.
- A pattern starting with `-` needs `-e`, because click consumes a bare `--`.
  grep's output is captured, so colour needs `--color=always`.
- This is a first persistent cache in glados. It is a cache, not an index:
  entries can be dropped at any time and are rebuilt on demand, so it fits
  0004's report shape.

## Alternatives

- **Keep the split, add a cached stdout mode to `transcribe`**: honours 0008
  literally, but the user loops over files in the shell to get grep's
  output per media file.
- **multitool command shelling out to `glados transcribe`**: passes the
  import boundary tests, but multitool would resolve a backend through a
  subprocess, which 0008 forbids in spirit.
- **Keep `srt-grep` beside `audio-grep`**: two overlapping commands for one
  job.
- **Key the cache by path**: cheaper (no checksum), but the cache would list
  every transcribed file.
