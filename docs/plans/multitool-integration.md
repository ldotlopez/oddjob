# Plan: finish integrating multitool into glados

Status: proposed (2026-11-06). Branch `worktree-multitool-port`, after `53eeaa8`.

## Context

multitool was ported from `ocdutils/u/tools` (decision 0003) and then fitted
into glados' model: every command that produces a file runs a `Job`; batches
go through `core/batch.run_batch`; glados' own tasks take `PATH...`; there is
one error tuple (`pipeline.JOB_ERRORS`); multitool commands live in
`multitool/commands/<tool>.py`.

What is left are smaller inconsistencies between the two tools, a boundary
held only by convention, and documentation that no longer matches the code.
Each step below is independent, keeps behavior unchanged unless it says
otherwise, and ends with `uv run ruff check . && uv run python -m unittest
discover -s tests` green.

## Steps

### 1. Same success output in both tools

Problem: glados tasks print `Wrote <dest>` per file (`cli_options.run_jobs`);
`jpgize`, `mp4ize` and `motionphotos merge` print nothing on success, because
they need a pre-check and a post-action (`--rm`) around the Job and so call
`run_batch` directly.

Change: make `run_jobs` take the per-item action instead of a `Job`
(`Callable[[T, BaseProgressReporter], Path]`, returning the written path) plus
a `label`. glados tasks pass `lambda path, reporter: job.run(path, reporter,
overwrite=...)`; `convert_all` and `merge` pass their actions and drop their
own `run_batch`/`finish_batch` calls.

Verify: CliRunner tests that `jpgize` and `merge` print `Wrote ...`; the
existing `run_jobs` test still passes.

### 2. Atomic landing on another filesystem

Problem: steps write temp files under `$TMPDIR`; `move_to_destination` uses
`shutil.move`, which across filesystems copies into the destination path
directly. A photo library on another disk gets a full, non-atomic copy, so an
interrupted `merge` or `strip -y` (in place) can leave a truncated original.

Change: in `pipeline.move_to_destination`, when `os.replace` fails with
`EXDEV`, copy (`shutil.copy2`) to a temp file in `dest.parent` and then
`os.replace` it over `dest`. Same-filesystem moves stay a plain rename. Steps
keep writing to `$TMPDIR`.

Verify: unit test that patches nothing but uses a destination on a different
filesystem when one is available (`/dev/shm` vs the temp dir), skipped
otherwise; plus a test that the sibling temp file is removed on failure.

### 3. Enforce the multitool → glados boundary

Problem: decision 0003 forbids multitool from importing `core/backends.py`,
`core/config.py`, `core/cli_common.py`, `core/text_backend.py`,
`glados.plugins` and `glados.tasks`, but nothing checks it.

Change: `tests/test_boundaries.py` parses every `multitool/**/*.py` with
`ast` and fails on a forbidden import; and checks that nothing under
`glados/` imports `multitool`. No new dependency.

Verify: the test passes now and fails when a forbidden import is added
temporarily.

### 4. One file-type helper

Problem: `multitool/media.py` and `core/inputs.media_type_filter` both guess
types with `mimetypes`.

Change: `media.is_image`/`is_video` build on `media_type_filter("image/")` /
`media_type_filter("video/")`; `media.py` keeps only what is multitool's own
(the extra video extensions, `converts_to_jpeg`, `converts_to_mp4`).

Verify: `MediaTests` unchanged and green.

### 5. Integration tests against the real tools

Problem: multitool's conversions are unit-tested with fake executables only;
the real-tool smoke run lives outside the repository.

Change: `tests/test_multitool_integration.py`, `*IntegrationTest` classes like
glados' backends, skipping when `magick`/`convert`, `exiftool` or
`ffmpeg`/`ffprobe` are missing: jpgize keeps tags (PNG text chunk ->
`IFD0:Artist`) and drops Orientation; mp4ize remuxes a generated MKV;
motion photo join/split round trip on real files; img-duplicates groups a
re-encoded copy.

Verify: runs locally (all tools installed here), skips cleanly without them.

### 6. `--dry-run` for glados tasks

Problem: every multitool command that changes files takes `-n`; glados tasks
do not, although their destinations are known without running anything.

Change: add `dry_run_option` to the four task commands; with `-n`, print
`input -> destination` per input from the Job's `dest_fn` and return before
the backend is resolved. Put the printing in `cli_options` next to
`run_jobs` so both tools share it.

Verify: CliRunner test that `rewrite -n DIR` prints the plan with no backend
configured.

### 7. Decide the command-module convention

Problem: glados keeps steps and click command together in
`tasks/<task>.py`; multitool separates domain modules from
`multitool/commands/<tool>.py` (as `architecture.md` asks). Both are
reasonable; two conventions in one repository are not.

Change: none until decided. Options: (a) keep both, documented as "task =
pipeline + command" vs "tool = domain + commands"; (b) split glados tasks into
`tasks/<task>.py` (steps) and `glados/commands/<task>.py`. Recommendation:
(a), since a glados task module is small and its steps exist only for that
command.

### 8. Documentation (each file needs explicit approval before editing)

- `docs/ARCHITECTURE.md`: module tree (`core/cli_options.py`, `inputs.py`,
  `batch.py`, `multitool/` with `commands/`); layers (backend-free core vs
  backend part of `core/`); Inputs section from "specified" to implemented,
  with the failure policy (continue, log, summary, exit 1) and the text
  tasks' own-output exclusion; `BytesStep`, `JOB_ERRORS`, reporter
  `remove()`.
- `README.md`: tasks take `PATH...`, `-o` only with one input; a multitool
  section (install with `uv sync --extra multitool`, commands, runtime
  binaries ImageMagick, exiftool, ffmpeg); remove the two finished roadmap
  items; Development: `uv sync --extra multitool` so image tests run.
- `.claude/rules/glados.md`: the multitool package, its import boundary,
  `commands/` layout, and that its image tests need the extra.
- `docs/decisions/0004` (new): "Every command that produces a file runs a
  Job; reports, renames and checks are plain functions under `run_batch`",
  and the multiple-input failure policy. 0003 stays as is.
- `pyproject.toml` description: drop the nonexistent `describe`/`tts`,
  mention multitool.

## Order

1 and 2 first (user-visible behavior), then 3 and 4 (cheap, guard the
result), 5 and 6, then 7's decision, and 8 last so the docs describe the
final state.
