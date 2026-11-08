# 0013. One overwrite policy: `-y` for the output, `--in-place` for the input

Status: accepted (2026-11-08)

Supersedes the in-place rule of 0004 ("Commands that rewrite files in place
refuse up front without `-y`"); the rest of 0004 stands.

## Context

`-y` meant two things. For most commands it replaced an existing output; for
`img-embed-description`, `date-copy --to exif`, `motionphotos merge` and
`motionphotos strip` without `-o` it was the permission to rewrite the input
itself (`require_overwrite`). 0010 had already given same-format commands
`--in-place` for that, and 0012 moved `photo-lint set-zone` to it, so the
remaining commands were the exception.

## Decision

For every command that produces a file:

1. If the output exists, that input fails and the rest of the batch goes on
   (`N done, M failed`, exit 1; 0004's batch policy).
2. `-y/--overwrite` replaces an existing output, never the input.
3. `--in-place` replaces the input atomically and implies `-y`; it excludes
   `-o` and comes with `--keep-mtime` (0010).
4. No command changes its input without `--in-place`. `require_overwrite` is
   removed from `filejobs`.

Commands that wrote in place now write `NAME.<infix>.<ext>` by default, and
skip earlier outputs with that infix when walking a directory:

| Command | Output |
|---|---|
| `date-copy --to exif` | `NAME.dated.<ext>` |
| `img-embed-description` | `NAME.described.<ext>` |
| `motionphotos strip FILE` | `NAME.still.jpg` (or `-o`) |
| `motionphotos merge PATH...` | `NAME.motion.jpg` |

Renames (`rename-by-hash`, `fix-extensions`, `date-copy --to name`) have the new
name as their output: rules 1 and 2 apply as they are. `date-copy --to mtime`
and `cleanup` produce no output file and are outside this policy;
`date-copy`'s `--in-place` and `--keep-mtime` need `--to exif`.

## Consequences

- Running one of the four commands above with `-y`, as before, leaves the
  original untouched and writes a new file; the old behavior needs
  `--in-place`.
- Results carry the time of the run unless `--keep-mtime`; `date-copy --to exif`
  no longer keeps the mtime by itself (it did through exiftool's `-preserve`
  on the input).
- Writing tags into a copy is one step, `dates.WriteTagsStep`, shared by
  `date-copy --to exif` and `photo-lint set-zone`.

## Alternatives

- **Abort the whole command when any output exists**: safer, but it changes
  0004's batch policy for every command.
- **Keep `-y` as the permission to rewrite in place**: one flag with two
  meanings depending on the command.
- **`NAME.fixed.<ext>` for every command**: uniform, but the name would not say
  what was done.
