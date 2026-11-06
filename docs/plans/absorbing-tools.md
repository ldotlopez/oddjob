# Plan: absorbing miscellaneous tools into glados and multitool

Status: draft (2026-11-06). Prerequisites not started; no tool ported yet.

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

| Tool | Source | Writes files? | Replaceable implementation? | External binaries / services | New Python deps | Destination | Done |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

## 2. Prerequisites (fix before the first port)

These are gaps in the current code that a new tool would copy. Each step is
independent, keeps behavior unchanged unless it says otherwise, and ends
with `uv run ruff check . && uv run python -m unittest discover -s tests`
green.

### 2.1 Single-file commands print nothing on success

Problem: 0004 says every command that writes a file prints `Wrote <dest>`.
`run_jobs` does, but `filejobs/cli_options.run_single_job` does not. The
commands that write a file through it are silent on success:

- `motionphotos join` (`multitool/commands/motionphotos.py`, one call);
- `motionphotos split` (two calls, one per destination: image, then video);
- `motionphotos strip` (one call, possibly in place with `-y`).

A new single-file command would inherit the silence. The `absorb-tool`
skill already describes the fixed behavior.

Change: `run_single_job` keeps the path `job.run` returns, prints
`Wrote <dest>` after the reporter context closes (so the line does not mix
with a live progress bar), and returns it. Failures stay a
`ClickException`, and nothing is printed for them. `split` then prints two
lines, which is correct since it writes two files. The callers need no
change.

Verify: in `tests/test_multitool_commands.py`, the existing
`test_motionphotos_join_and_split` and `test_strip_in_place_needs_overwrite`
also assert `Wrote <dest>` in the output: once for `join`, once per
destination for `split`, and for `strip -y`, but not for the refused
`strip` without `-y`.

### 2.2 Two dry-run formats

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

### 2.3 Docstrings that point at code that no longer exists

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

### 2.4 rich's `TaskID` in `RichProgressReporter`

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

- **Record the classification as a decision?** The skill's "Classify" step
  (not absorbed / glados / multitool / filejobs, mixed tools split along the
  model boundary) is new policy. It could become decision 0007, "Where a new
  tool goes", extending 0003's scope section, which covered only the
  ocdutils ports.
- **Which tools to absorb, and from where.** Section 1 stays empty until the
  candidates are listed.

## Order

The section 2 prerequisites come first, since each is small and
independent. Then the tools, one per commit, each following the
`absorb-tool` skill: glados tasks and multitool commands are independent of
each other. A tool that pushes code into `filejobs` goes alone, with its own
decision record.
