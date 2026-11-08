# 0012. `photo-lint set-zone` writes a fixed copy

Status: accepted (2026-11-08)

Supersedes 0011, whose rules stay in force except where noted.

## Context

0011 had `set-zone` rewrite each image in place, behind `-y`, like
`date-copy --to exif`. That breaks two rules other commands follow: a command
whose output keeps the input's format writes `NAME.<infix>.<ext>` and replaces
the input only with `--in-place` (0010), and `-y` only overwrites an existing
destination. Its `--replace` flag also read like "replace the file".

## Decision

- `photo-lint` is a group of image metadata checks and fixes. `check` prints
  `PATH: CODE` for every failing check (`photolint.CHECKS`; the first is
  `no-zone`, a capture date without a valid offset) and exits 1 if any.
- `set-zone --zone NAME` takes an IANA zone (matched ignoring case) and treats
  each EXIF date as a wall-clock time in it. Each date gets the offset the zone
  had at its own time, in its own tag: `DateTimeOriginal` →
  `OffsetTimeOriginal`, `CreateDate` → `OffsetTimeDigitized`, `ModifyDate` →
  `OffsetTime`. The dates are not changed.
- The result is a `Job` (`SetOffsetsStep`: a copy of the image with the offsets
  written) landing as `NAME.fixed.<ext>`. It takes the same-format options of
  0010: `--in-place` replaces the input, `--keep-mtime`, `-o` for one input, and
  `-y` only to overwrite an existing destination. Earlier `NAME.fixed.<ext>`
  outputs are not inputs.
- Offsets already recorded are kept; `--replace-offsets` (0011's `--replace`)
  rewrites them. Images with nothing to write are skipped.
- In the repeated hour at the end of daylight saving the first occurrence is
  taken, as `dates.local_time` does. A time in the skipped hour does not exist
  in the zone: that file fails, and the batch goes on.
- Images only: QuickTime dates are UTC by specification (0009).
- `filejobs.cli_options.run_jobs` takes `prior` reports, so a command that plans
  under `run_batch` and then writes through `run_jobs` reports both passes in
  one summary.

## Consequences

- Running `set-zone` on a folder no longer changes any original unless
  `--in-place` is given; results carry the time of the run unless `--keep-mtime`.
- `set-zone -n` needs exiftool, since the plan depends on the dates; its lines
  are exiftool calls with `-o DEST`.
- `date-copy --to exif` and `img-embed-description` still write in place behind
  `-y`, which this record does not change.

## Alternatives

- **Keep 0011's in-place write**: one command less like the others, and `-y`
  meaning "rewrite the input" there but "overwrite the destination" elsewhere.
- **`-y` or `--replace` replacing the original**: contradicts 0010's
  `--in-place`.
