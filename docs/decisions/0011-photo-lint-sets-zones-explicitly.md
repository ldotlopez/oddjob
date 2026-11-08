# 0011. `photo-lint set-zone` records a zone the user names

Status: accepted (2026-11-08)

## Context

Cameras write EXIF dates as wall-clock times without a zone. Decision 0009
made `date-copy` keep the offset a file records, and rejected guessing a zone
for files that record none: a library may span several zones. Those files
stay ambiguous until someone who knows where they were taken says so.

## Decision

- `photo-lint` is a group of metadata checks and fixes for images.
  `photo-lint check` prints `PATH: CODE` for every failing check
  (`photolint.CHECKS`; the first is `no-zone`, a capture date without a valid
  offset) and exits 1 if there is any.
- `photo-lint set-zone --zone NAME` takes an IANA zone (matched ignoring case)
  and treats each EXIF date as a wall-clock time in it. Each date gets the
  offset the zone had at its own time, in its own tag: `DateTimeOriginal` →
  `OffsetTimeOriginal`, `CreateDate` → `OffsetTimeDigitized`, `ModifyDate` →
  `OffsetTime`. The dates are not changed.
- Offsets already recorded are kept; `--replace` rewrites them.
- In the repeated hour at the end of daylight saving the first occurrence is
  taken, as `dates.local_time` does. A time in the skipped hour does not exist
  in the zone: that file fails, and the rest of the batch goes on.
- Images only. QuickTime dates are UTC by specification (0009), so "the stored
  time is the wall clock" does not apply to videos.

## Consequences

- The zone guess 0009 rejected for `date-copy` is now an explicit choice for a
  set of files the user picks; `date-copy` is unchanged.
- Once offsets are written, `date-copy` reads those files as exact instants.
- `set-zone -n` needs exiftool, since the plan depends on the dates.

## Alternatives

- **`--zone` on `date-copy`**: mixes copying dates with assigning zones, and is
  close to what 0009 rejected.
- **One offset per file**: a file whose dates fall on both sides of a daylight
  saving change would get a wrong offset for one of them.
- **Taking the offset before the change for a skipped time**: every file gets an
  offset, but this one would be silently an hour off.
