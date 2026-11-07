# 0006. audio-grep: grep over cached transcripts

Status: accepted (2026-11-07)

## Context

Searching what was said in a set of recordings meant transcribing each one
to an `.srt` sidecar and searching the sidecars. That took two commands, left
an `.srt` next to every file whether or not it was wanted, and a dedicated
search command offered less than grep's options.

## Decision

- `audio-grep` is one command. It reuses the `transcribe` backends, with no
  entry-point group of its own (0005, rule 2).
- It runs the system `grep`. Arguments that are existing directories or
  audio/video files are the inputs; everything else goes to grep unchanged,
  so grep's option grammar (GNU grep, ugrep, ...) is never parsed here. Its
  own options are long-only (`--backend`, `--model`, `--language`,
  `--transcript-format`, `--log-level`).
- Each transcript is written to a temporary file, grep runs once over all of
  them, and the temporary paths in its output are replaced by the media
  paths. The exit status is grep's, or 2 if an input could not be
  transcribed.
- No sidecar is written. Transcripts are stored as segments, so any
  `--transcript-format` can be rendered from them, in the user cache (0007).
  The key covers the content's SHA-256, the mtime, and `--backend`,
  `--model` and `--language` as given.
- The grep subprocess is an adapter in `oddjob/lib/grep.py`.

## Consequences

- One command searches recordings directly, with every grep option. A second
  search of a file costs a checksum, not a transcription, and the backend
  loads only on a cache miss.
- `--backend`/`--model` are keyed as given, so the same model named two ways
  (default vs. explicit) is transcribed twice.
- A pattern starting with `-` needs `-e`, because click consumes a bare `--`.
  grep's output is captured, so colour needs `--color=always`.
- Plain `grep` still covers `.srt` sidecars written by `transcribe -f srt`.

## Alternatives

- **`transcribe -f srt` plus a separate search command**: the setup this
  replaces.
- **A cached stdout mode in `transcribe`**: the user then loops over files in
  the shell to get grep's output per media file.
- **Key the cache by path**: no checksum, but the cache would list every
  transcribed file.
