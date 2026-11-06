# Plan: absorbing miscellaneous tools into glados and multitool

Status: draft (2026-11-06). Prerequisites done (2.1, 2.3, 2.4; 2.2 needed
no code); mediatools inventoried and ported: six tools, removebg left out by
the user (section 1).

## Context

The multitool integration (`multitool-integration.md`, decisions 0003–0006)
left the repository with three packages and one way of doing things:

- `filejobs/`: the backend-free core (`Job`, steps, destination policies,
  `JOB_ERRORS`, `run_batch`, `run_jobs`, input expansion, shared click
  options, progress, the ffmpeg runner). Imports neither tool.
- `glados/`: model-backed tasks. A task Protocol, backends in
  `glados/plugins/` declared through entry points, and config.
- `multitool/`: file utilities with a single implementation, no backends
  or config.

Both tools share one layout (0005) and one batch policy (0004);
`tests/test_boundaries.py` enforces the import boundaries and where click
may be imported.

This plan brings further tools (scripts, ocdutils leftovers, one-off
utilities) into that structure without changing it. The reusable procedure
(classification, command shapes, porting steps, tests, checklist, docs) is
the project skill **`absorb-tool`** (`.claude/skills/absorb-tool/`); this
plan holds what is specific to this round: the inventory, the prerequisites
to fix first, and the open decisions.

## 1. Inventory

One row per candidate tool; columns as defined in the skill's "Intake"
step. New Python dependencies need approval before porting starts.

Source of this round: `ocdutils/mediatools/` (`mt` below). Already absorbed
from it, so not listed: `sidecars`, `motionphotos`, `formats` (`jpgize`,
`mp4ize`), `mediahash` (`img-hash`), `crc32-rename` (`hash-rename`),
`find-duplicates` with averagehash (`img-duplicates`), `audio transcribe`
(`glados transcribe`), and `texttransform` `rewrite`/`summarize` (glados'
tasks; tone and language become `rewrite -i`).

Destinations of the ported rows were settled with the user; the not-absorbed
rows stay proposals.

| Tool | Source | Writes files? | Replaceable implementation? | External binaries / services | New Python deps | Destination | Done |
|---|---|---|---|---|---|---|---|
| `fix-extensions` | `mt/filesystemfixes.py` | renames (lowercase extension, `jpeg`→`jpg`, `mpeg`→`mpg`, `tif`→`tiff`) | no | — | — | multitool `fix-extensions`, rename shape | `7f25d23` |
| `photos-check` | `mt/photos-check.py` | only reports (corrupt or unknown-type images) | no | — | — (Pillow, `multitool` extra) | multitool `img-check` (report on stdout) | `7b72810` |
| `autocrop` | `mt/imgedit.py` | new file per input (crop to the alpha bbox) | no | — | — (Pillow) | multitool `autocrop`, file producer | `df3a757` |
| `removebg` | `mt/imgedit.py` | new file per input | yes (rembg models, remote APIs) | model download | `rembg` (onnxruntime) | not absorbed (user decision; would need `rembg`) | — |
| `translate` | `mt/texttransform.py` | new file per input | yes (text backends) | text backend | — | glados `translate`, `FILE.<language>.<ext>` | `61722e7` |
| `describe-image` | `mt/generativeimages.py` | report; `-w` writes an EXIF comment in place | yes (OpenAI vision, LAVIS, Ollama) | backend; `exiftool` | — | split: glados `describe` (`a2f4466`, `0dd4e23`) + multitool `img-caption` | `58097ca` |
| `agrep` | `mt/audio.py` | only reports (grep over transcriptions) | only the transcription | — | — (no `pysrt`) | multitool `srt-grep` over `glados transcribe -f srt` sidecars | `5c3c4fd` |
| `create-image` | `mt/generativeimages.py` | one file from a prompt, no input file | yes | OpenAI | — | not absorbed: no command shape takes a prompt instead of `PATH...` | |
| `emojize` | `mt/texttransform.py` | stdout only | yes | text backend | — | not absorbed: `rewrite -i` covers it | |
| `embeddings` | `mt/embeddings.py` | an sqlite index | yes | OpenAI | `numpy`, `python-magic` | not absorbed: an index fits no command shape | |
| `cv2histogram` | `mt/backends/cv2histogram.py` | — | second `img-duplicates` method | — | `opencv` | not absorbed: decision 0003 chose the average hash | |

## 2. Prerequisites (fix before the first port)

These are gaps in the current code that a new tool would copy. Each step is
independent, keeps behavior unchanged unless it says otherwise, and ends
with `uv run ruff check . && uv run python -m unittest discover -s tests`
green.

### 2.1 Silent on success (decision 0007): done (`6b7e9d9`)

Done. `foundation.loglib` applies a bare `--log-level` level only to the
app logger (`*` resolves to it), so `logging_options_for` copies the app
level to `filejobs` and then applies the spec again, letting an explicit
`filejobs:<level>` rule win.

Problem: the tools should print nothing on success unless `-v` is given,
but they don't follow that convention:

- `run_jobs` prints `Wrote <dest>` for every written file (0004), covering
  `transcribe`, `rewrite`, `summarize`, `expand`, `jpgize`, `mp4ize` and
  `motionphotos merge`. `run_single_job` (`motionphotos join`, `split`,
  `strip`) is silent, so the two shapes also disagree with each other.
- Progress ignores verbosity. Rich bars are not transient, so a finished
  batch leaves its overall bar and a single job its step bars. Off a
  terminal, `PlainProgressReporter` `print`s `starting`, every 10% and
  `done` for every task, which is hundreds of lines for a directory.
- `-v` cannot reveal any of it from the shared code:
  `logging_options_for(app_logger)` sets only the app logger's level
  (`glados` or `multitool`), and `filejobs.*` stays at `warning`.

Implements decision 0007 (accepted; 0004 partly superseded by it).

Change, all in `filejobs/`:

1. `cli_options.py`: add `LOGGER = logging.getLogger(__name__)`.
   - `run_jobs` logs `wrote %s` at INFO inside its per-item wrapper, when
     each file lands, and drops the `written` list and the `click.echo`
     loop.
   - `run_single_job` logs the same after the Job returns.
   - `finish_batch` is unchanged: summary on stderr and exit 1, only on
     failure.
2. `cli_options.logging_options_for`: after `setup_logger_from_click`, give
   `logging.getLogger("filejobs")` the app logger's effective level, unless
   `--log-level` was given, in which case its rules decide per logger (for
   example `--log-level 'multitool:info,filejobs:debug'`). When
   implementing, confirm in `foundation.loglib` what a bare level in
   `--log-level` applies to (`*`), so that `--log-level info` alone also
   reaches `filejobs`.
3. `progress.py`:
   - `RichProgressReporter` uses `Progress(..., transient=True)`.
   - `PlainProgressReporter` sends its lines to
     `logging.getLogger(__name__).info(...)` instead of
     `print(..., file=sys.stderr)`, with the same text and the same
     10% throttle; `sys` is no longer needed.

None of the callers in `glados/commands/` or `multitool/commands/` change.

Verify:

- `tests/test_filejobs.py`: in `test_run_jobs_continues_and_exits_1_on_failure`,
  `Wrote` is no longer in the output, `assertLogs("filejobs", "INFO")` holds
  `wrote <tmp>/b.out`, and the summary and exit 1 are unchanged.
- A new test: with `PlainProgressReporter`, a task's lines arrive as INFO
  records on `filejobs.progress` and nothing is written to stderr directly.
- A new test: a `CliRunner` command decorated with
  `logging_options_for("multitool")` and run with `-v` leaves the
  `filejobs` logger at INFO; run without flags, it stays at WARNING.
- `tests/test_multitool_commands.py`:
  - `merge` (line 48) and `test_jpgize_prints_what_it_wrote` (line 119;
    rename it to `..._logs_what_it_wrote`) assert the file exists, the
    `wrote` log record is present, and stdout is empty;
  - `join`, `split` (two records) and `strip -y` assert the `wrote` records;
  - the refused `strip` without `-y` logs none.
- A manual check on a terminal: `multitool jpgize DIR` leaves nothing on
  screen on success, and `multitool -v jpgize DIR | cat` shows the progress
  and `wrote` lines on stderr.

Docs to propose after the code change (each needs approval):

- `README.md`: the `-v` row of the options table, and the multitool
  paragraph that says `jpgize`, `mp4ize` and `merge` print `Wrote <dest>`.
- `docs/ARCHITECTURE.md`: "Inputs" (`run_jobs` prints `Wrote`), and
  "Console and logging" (transient bars, plain progress as INFO, `filejobs`
  following the app's verbosity).
- `.claude/rules/glados.md`: the console and logging bullet.

### 2.2 Two dry-run formats: done (no code change)

Problem: glados' tasks print `input -> destination` through
`cli_options.print_plan`. multitool's commands print each planned
operation's `describe()` (`convert a.png -> a.jpg, then remove a.png`). A
new command has to pick one.

Decision, no code change: keep both. A plan that is only a destination per
input uses `print_plan`. A plan with more than one action per item (convert
then remove, merge then remove, rename) is a list of frozen dataclasses
with `describe()`. The extra actions are what a rich plan is for, and
forcing them into `in -> dest` would hide them. `docs/ARCHITECTURE.md`
("Inputs", last paragraph) already states the rule, and the `absorb-tool`
skill repeats it for porters.

Verify: nothing to run.

### 2.3 Docstrings that point at code that no longer exists: done (`381073e`)

Done, plus one comment the list missed (`glados/tasks/transcribe.py`).

Problem: these refer to `transcribe_sidecar.py`, the pre-glados script,
which is not in the repository:

- `filejobs/pipeline.py`: the module docstring ("task-agnostic remainder of
  transcribe_sidecar.py's TranscriptionJob") and `Job`'s docstring
  ("unchanged from transcribe_sidecar.py's TranscriptionJob");
- `filejobs/progress.py`: the module docstring ("Lifted from
  transcribe_sidecar.py");
- `filejobs/runners.py`: the module docstring ("Unchanged from
  transcribe_sidecar.py").

Also, `multitool/cli.py` cites only decision 0003, while its layout and
imports follow 0005 and 0006.

Change: rewrite those docstrings to describe what the code does now. For
example, `Job` checks the destination before the first step and again right
before the move. The pipeline module docstring should name the current step
lists: transcribe's two steps, the text tasks' one `TextStep`, multitool's
`BytesStep`. `multitool/cli.py` should cite 0003, 0005 and 0006. Docstrings
and comments only.

Verify: no reference to `transcribe_sidecar` is left in `filejobs/`,
`glados/` or `multitool/`. Search those three directories for `*.py` only.

### 2.4 rich's `TaskID` in `RichProgressReporter`: done (`903e659`)

Done; the README roadmap line is in the uncommitted README of the main
checkout and is left to the user.

Problem: this is the README roadmap note, which is still uncommitted.
`BaseProgressReporter` uses plain `int` task ids, so the plain reporter,
`batch.TransientStepReporter` and `tests/support`'s fake need no rich
import. That part is right. But `RichProgressReporter` passes those ints
straight to rich, which types them as `TaskID` (a `NewType` of `int`).
Running pyright on `filejobs/progress.py` reports 9 errors, all in
`RichProgressReporter`:

- `update`, `complete` and `remove` pass `int` where rich expects `TaskID`;
- `update` builds a `dict[str, float]` and splats it into `Progress.update`,
  whose other keywords include `refresh: bool`, so the types do not match;
- `__enter__` and `__exit__` forward to `Progress.__enter__` and
  `Progress.__exit__`. The latter is called with `*exc_info: object`, while
  rich expects the exception type, value and traceback.

It works at runtime, since `TaskID` is an `int`, but every new reporter
call copies the pattern.

Change, confined to `RichProgressReporter`:

- wrap ids with `TaskID(task_id)` (imported from `rich.progress`) where they
  go to rich, and keep `int` in the Protocol and its other implementations;
- call `Progress.update(TaskID(task_id), completed=completed, total=total)`
  with explicit keywords, without the dict. rich leaves the total unchanged
  when it is `None`, which is what the dict did by omitting the key;
- use `Progress.start()` and `Progress.stop()` in `__enter__` and
  `__exit__`. That is all rich's own context manager does, and the
  Protocol's `*exc_info: object` signature stays.

Then drop the roadmap line from the README, which needs approval as a
README edit.

Verify: `uv run --with pyright pyright filejobs/progress.py` reports 0
errors. This is a one-off check, since pyright is not part of the repo's
tooling (pre-commit runs ruff and pyupgrade only). Adding a type checker is
a separate decision. The existing reporter tests in `tests/test_filejobs.py`
stay green.

## 3. Decisions to take


- **Record the classification as a decision?** Decided: yes, as
  [decision 0008](../decisions/0008-where-a-new-tool-goes.md), "Where a new
  tool goes", extending 0003's scope.
- **Which tools to absorb, and from where.** Decided for this round:
  ocdutils `mediatools/`, section 1.

## Order

The section 2 prerequisites come first, since each is small and
independent. Then the tools, one per commit, each following the
`absorb-tool` skill: glados tasks and multitool commands are independent of
each other. A tool that pushes code into `filejobs` goes alone, with its own
decision record.
