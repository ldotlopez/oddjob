# Backlog

Every open, unscheduled piece of work in oddjob, in one place. Each item that
changes a shared option set or an approach is settled in a decision record
before it is built. Scheduled work does not live here: when an entry is
scheduled it moves to the plan for that work and leaves this file.

Last updated: 2026-11-27

## General

- **Audit leftovers (2026-11-26).** A complexity and duplication audit of
  `filejobs/`, `oddjob/` and `tests/` (313 tests, 1 skipped, green before and
  after; ruff clean) applied its changes in `e071ae8`, `a8fddaa`, `9b29453`,
  `f215f32` and `59ad1ba`. What remained open:
  - *Proposed, awaiting a decision:*
    - Optionally remove the `if __name__ == "__main__"` blocks in the task
      command modules (`oddjob/commands/`). They are leftovers of the
      standalone-tool idea that decision 0003 dropped, and none of the 15 file
      commands has one. They were left in because removing them stops
      `python -m oddjob.commands.<task>` from working.
  - *Documentation edits awaiting approval* (the project rule that docs change
    only with explicit permission overrides the global "docs land with the
    code" rule, so none were made):
    - `docs/ARCHITECTURE.md`, the `cli_options.py` line in the layout: add
      `run_same_format_jobs` (`filejobs/cli_options.py`, added in `e071ae8`:
      the shared run body of `rewrite`, `summarize`, `expand`, `translate` and
      `img-trim`).
    - `docs/ARCHITECTURE.md`, "Contracts": add the missing Protocols
      `Speaker`, `Translator`, `Describer` (inaccurate before the audit).
    - `docs/ARCHITECTURE.md`, "To add a backend": `uv sync` →
      `uv sync --all-extras`; a plain sync uninstalls the `images` extra
      (`.claude/rules/oddjob.md`). Inaccurate before the audit.
  - *Left alone on purpose:*
    - `_format_srt_timestamp` and `_format_vtt_timestamp` in
      `oddjob/lib/transcribe.py` differ by one character (`,` vs `.`); each
      belongs to its own output format (SRT, WebVTT) so each can change on its
      own.
    - The single-entry `_FACTORIES` registry in `oddjob/plugins/piper.py`
      could be a plain `if`, but it mirrors `whisper.py` and its
      unknown-backend error is tested.

## Transcription

- **whisper.cpp on the AMD Ryzen AI NPU.** whisper.cpp ≥ 1.9 can offload the
  encoder to the XDNA NPU via VitisAI (`-DWHISPER_VITISAI=1`); no oddjob change
  is needed, only the host setup:
  - `amdxdna` kernel driver (mainline since 6.14, or AMD's out-of-tree
    `xdna-driver`) and the NPU firmware for the chip revision
    (`/usr/lib/firmware/amdnpu/17f0_20`);
  - XRT (`xrt-smi examine` must list the NPU) and FlexML runtime, both sourced
    before building and running;
  - rebuild whisper.cpp with `-DWHISPER_VITISAI=1`, and fetch each model's
    `.rai` encoder cache with `models/download-vitisai-model.sh <model>`;
  - verify: `whisper-cli` prints `VITISAI = 1` and logs the offload mode.

  Cheaper interim step: build with `-DGGML_VULKAN=1` to use the integrated GPU.

## Tagging

- **Text from PDF and other binary documents in `tag`.** Today `tag` sends a
  document to `rewrite` with its name and mimetype, plus its content only when
  it is `text/*`; there is no PDF extraction, by design of the first version
  (no new dependencies). Extracting text from PDF and other binary formats
  would need an approved dependency (CLAUDE.md, "Dependency Policy") and
  changes the cached value, so bump the `tag` cache layout version
  (decision 0007).

## Features

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
  - Next step, once real iOS samples exist (see "Integration tests on real
    files" below): open both variants in an Android gallery. If the MOV
    trailer plays, let `merge` accept `.mov`; if not, let `merge` remux a
    `.mov` sidecar through `Mp4RemuxStep` before joining. HEIC stays a
    `jpgize` step before `merge`.
- **Text input for the text tasks.** `rewrite`, `summarize`, `expand` and
  `translate` take only `PATH...` today. Let them also take stdin (`-`, or a
  pipe) and text from the command line (`--text`/`-t`), as `speak` already
  does (`commands/speak.py`). Unlike `speak`'s WAV, text output can go to
  stdout, so `-o` need not be required for stdin and `--text`. Share the
  input handling between the five commands instead of copying `speak`'s. It
  adds an input shape to 0004's command shapes, so it needs its own decision
  record.

## Inconsistencies

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
