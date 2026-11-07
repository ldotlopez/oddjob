# Backlog

Open work found while absorbing tools. Each item that changes a shared
option set or an approach is settled in a decision record before it is built.

## Features

- **`--in-place` for every file transformation.** Done for `img-reduce`: the
  result replaces the original atomically (the `Job` lands its temp file on
  the input's own path), so no `NAME.<infix>.<ext>` is left behind. Offer the
  same option on the other file producers (`img-trim`, `jpgize`, `mp4ize`,
  and the text tasks where output and input formats match). It changes a
  shared option set, so it needs its own decision record.
- **`--keep-mtime` (or similar) next to `--in-place`.** Copy mtime, atime,
  permissions and the like from the original onto the result. Today it
  depends on the step: `BytesStep` (`img-trim`, `img-reduce`,
  `motionphotos`) and `mp4ize`'s remux already call `shutil.copystat`;
  `TextStep` (the text tasks) does not. Decide in the same record as
  `--in-place` whether it is an option or the default.
- **Image commands keep all metadata.** Every image-manipulating command must
  carry the input's metadata over. Today `img-trim` and `img-reduce` keep
  EXIF and the ICC profile (`imgedit._encode`), and `jpgize` copies all tags
  with exiftool. XMP and IPTC are lost in the Pillow-based edits (Pillow only
  rewrites `exif` and `icc_profile`); `ExifTool.copy_tags` after the edit
  would cover every format. Check each new image command against this rule.
- **iOS motion photos (`jpeg`/`heic` + `mov`).** `motionphotos merge` pairs
  only `.jpg`/`.jpeg` with `.mp4`; iOS exports Live Photos as `.jpeg` +
  `.mov` or `.heic` + `.mov`.
  - JPEG + MOV can be joined at the byte level (an iPhone MOV starts with
    `ftyp qt  `), but `motionphotos.is_mp4` checks the MP4 major brand and
    rejects MOV, and `plan_merges` filters on `.mp4`. Unverified: whether
    Google Photos and Samsung Gallery play a QuickTime-branded trailer;
    Google's Motion Photo format describes it as MP4.
  - Remuxing first is lossless and cheap: `mp4ize`'s step copies video and
    audio and, with ffmpeg's default stream selection, drops the `mebx`
    Apple metadata track that MP4 cannot hold.
  - HEIC + MOV cannot be joined as-is: the `MotionPhoto_Data` trailer is a
    JPEG layout. Either convert with `jpgize` (lossy) or write a HEIF motion
    photo, a different container and a new writer.
  - Next step, once real iOS samples exist: open both variants in an Android
    gallery. If the MOV trailer plays, let `merge` accept `.mov`; if not, let
    `merge` remux a `.mov` sidecar through `Mp4RemuxStep` before joining.
    HEIC stays a `jpgize` step before `merge`.

- **Text input for the text tasks.** `rewrite`, `summarize`, `expand` and
  `translate` take only `PATH...` today. Let them also take stdin (`-`, or a
  pipe) and text from the command line (`--text`/`-t`), as `speak` already
  does (`commands/speak.py`). Unlike `speak`'s WAV, text output can go to
  stdout, so `-o` need not be required for stdin and `--text`. Share the
  input handling between the five commands instead of copying `speak`'s. It
  adds an input shape to 0004's command shapes, so it needs its own decision
  record.

## Inconsistencies

- **Plans that cannot know the outcome.** Without the `images` extra, `-n`
  of `img-trim` and `img-reduce` lists every candidate, including images that
  will fail (no transparency) or be skipped (already small enough). Document
  it, or check sizes in `-n` when the extra is installed.
- **Directory inputs.** `filejobs.inputs.expand_inputs` yields files only, so
  `cleanup` walks the trees itself to reach directories. If a second command
  needs directories, move that walk to `filejobs` (decision 0005, rule 4).
- **Different quality defaults.** `imgedit` saves lossy formats at quality
  90; `jpgize` (ImageMagick) keeps ImageMagick's own default. Settle one
  quality policy for every image writer.

## Performance

- **`date-copy` starts one exiftool process per file** for reads and writes,
  which is slow on large libraries. Use exiftool's `-stay_open` mode, or one
  `-json` call per directory.
- **`date-copy --to name` reads every file in full for the crc32 while
  planning**, also with `-n`, which is slow on videos. Acceptable for now,
  since `rename-by-hash` does the same.

## Edge cases

- **`date-copy` and DST.** A wall-clock time in the repeated hour at the end
  of daylight saving is ambiguous. `astimezone()` takes the first one, so
  `--to mtime` may be an hour off for such files.

## Tests

- **Integration tests on real files.** Today's integration tests build their
  fixtures (ImageMagick gradients, ffmpeg test patterns, a minimal Shotwell
  schema), so device quirks go untested. Add a sample set that is never
  committed (privacy, size): a directory named by `ODDJOB_TEST_SAMPLES` in
  `tests/integration.env`, with `*IntegrationTest` classes that skip when it
  is unset. The user will provide:
  - an iPhone Live Photo export, as both HEIC + MOV and JPEG + MOV
    (`motionphotos`, `jpgize`, `mp4ize`, the iOS item above);
  - a Samsung or Google motion photo JPEG (`motionphotos check/split/strip`);
  - camera and phone JPEGs with `DateTimeOriginal` and `OffsetTimeOriginal`,
    and a phone MP4/MOV with QuickTime dates (`date-copy`);
  - a large JPEG/HEIC (over 2160 px) with EXIF orientation, an ICC profile
    and XMP/IPTC (`img-reduce`, `img-trim`, the metadata item);
  - an animated GIF or WebP, a transparent PNG, a truncated JPEG
    (`img-reduce`, `img-trim`, `img-check`);
  - a copy of a real Shotwell `photo.db` with the matching files
    (`date-copy --from shotwell`);
  - a folder copied from macOS and Windows with `.DS_Store`, `._NAME`,
    `Thumbs.db` and `desktop.ini` (`cleanup`).
- **The `whisper` (OpenAI CLI) backend has no tests yet.**
