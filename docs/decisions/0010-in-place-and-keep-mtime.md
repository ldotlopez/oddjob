# 0010. `--in-place` and `--keep-mtime` on same-format commands

Status: accepted (2026-11-08)

## Context

`img-reduce` has `--in-place`: the result replaces the input atomically
(`same_path` as the destination function), so no `NAME.<infix>.<ext>` stays
behind. The other commands whose output has the input's extension, and so use
`infix_destination` (decision 0004), have no way to do the same.

Timestamps are inconsistent. `BytesStep` (`img-trim`, `img-reduce`,
`motionphotos`), `JpegConversionStep`, `Mp4RemuxStep` and `CaptionStep` call
`shutil.copystat` unconditionally; `TextStep` (`rewrite`, `summarize`,
`expand`, `translate`) does not. Each step is deciding for itself, and the
user cannot choose.

## Decision

**`--in-place`**

- Offered by every command whose output keeps the input's format:
  `img-trim`, `img-reduce`, `rewrite`, `summarize`, `expand`, `translate`.
  Commands that change the format (`jpgize`, `mp4ize`, `describe`, the audio
  tasks) do not get it: their output is a different file, not a replacement.
- It is the same mechanism for all of them: the destination function returns
  the input's path, the job lands its temp file there atomically, and it
  implies `-y` (the user asked to replace). It is mutually exclusive with
  `-o/--output`.
- The option and its check live with the shared file options
  (`filejobs.cli_options`), not in each command.
- It applies to files only. Text read from stdin or `--text` has no file to
  replace.

**`--keep-mtime`**

- Off by default: a command produces a new file, which has a new
  modification time. Whoever wants the original times says so.
- With it, the result gets the original's access and modification times.
- It is applied once, when the job lands the result, and not in each step.
  Steps stop calling `shutil.copystat`. Every file-producing command that
  has `--in-place` also takes `--keep-mtime`; so do the other commands that
  write a file from a single input (`jpgize`, `mp4ize`,
  `img-embed-description`, `motionphotos`), because their steps lose the
  behavior they have today.
- Permissions are not a timestamp option. Temp files are created owner-only
  while a step writes them, which keeps a half-written result private; the
  job gives the result the input's mode just before it lands, so a replaced
  file does not change who can read it. The input's times are read before
  any step runs, because reading it can update its access time.

## Consequences

- Behavior changes for the steps that copied times today (`img-trim`,
  `img-reduce`, `motionphotos`, `jpgize`, `mp4ize`, `img-embed-description`):
  results now carry the time of the run unless `--keep-mtime` is given. Tests
  that check the copied time must pass the option.
- The text tasks gain the same two options without a step of their own.
- A date-based library (`date-copy --to mtime`, sorting by time) is not
  silently kept in order any more; users who rely on it pass `--keep-mtime`.
- Metadata inside the file (XMP, IPTC) is a separate matter and stays in the
  backlog.

## Alternatives

- **Keep-times as the default**: matches today's image commands, but it
  would give a freshly written file an old time, which makes
  "what did this run change?" harder to answer.
- **One option per step type**: whatever suits each step, but the user would
  learn a different rule per command.
- **`--in-place` only for images**: leaves the text tasks leaving
  `NAME.rewrite.<ext>` files that the user then moves by hand.
