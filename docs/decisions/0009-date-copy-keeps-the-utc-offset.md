# 0009. `date-copy` keeps the UTC offset a file records

Status: accepted (2026-11-08)

## Context

Cameras write EXIF dates as wall-clock times without a zone. `date-copy`
read them as local time and wrote them back the same way, so a time in the
repeated hour at the end of daylight saving (e.g. 02:30 on 2019-10-27 in
Europe/Madrid) always resolved to the first occurrence, and `--to mtime` could
be an hour off. The information to tell them apart exists in the files:
`OffsetTime*` in EXIF, UTC in QuickTime.

## Decision

- Reading (`dates.date_from_tags`): a date keeps the UTC offset its file
  records. For an EXIF date that is the matching `OffsetTimeOriginal` or
  `OffsetTimeDigitized` tag (`dates.OFFSET_TAGS`); for a video, whose
  QuickTime dates are read through exiftool's UTC conversion, the offset
  printed after the date. Without a valid offset the date is read as local
  time, as before (`dates.recorded_time`).
- Writing (`dates.ExifChange.tags`): an image gets its dates plus
  `OffsetTimeOriginal`, `OffsetTimeDigitized` and `OffsetTime`, replacing any
  stale offset; a video's dates carry the offset in their value and
  are stored as UTC (`-api QuickTimeUTC`). `ExifTool.write_tags` takes the
  tag-to-value mapping instead of one value for many tags.
- Filenames do not change: the wall-clock part is formatted as before.
- A wall-clock time with no recorded offset, in the repeated hour, still
  resolves to the first occurrence (`dates.local_time`). Nothing can settle
  it.

## Consequences

- The same instant is kept when a file is copied between zones or across the
  end of daylight saving, for files that record an offset.
- Writing EXIF dates now also writes three offset tags. Files whose dates
  came from `--from mtime` or `--from name` get the offset of the system zone
  at that time.
- Files without an offset keep the old, ambiguous reading.

## Alternatives

- **Document the first-occurrence rule only**: no change to what is written,
  but the error stays for files that do record the offset.
- **Offer an option to set the zone**: moves the guess to the user and
  cannot cover a library shot across several zones.
