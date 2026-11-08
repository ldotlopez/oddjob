# 0004. Jobs, batches, and silent success

Status: accepted (2026-11-07); its in-place rule superseded by 0013

## Context

Every command takes `PATH...` and acts on every file it expands to. Without
one policy, commands wrote files in several ways (direct writes,
`shutil.move`, in-place rewrites), handled a failing input differently, and
printed a line per written file and per progress step, so a cron or CI run
over a directory wrote hundreds of lines on success. Verbosity flags applied
only to the app's logger, so the shared code's INFO records never showed.

## Decision

**Writing files**

- Every command that writes a file runs a `filejobs.pipeline.Job`: steps
  write temp files, the destination is re-checked (`-y` to replace), and the
  result lands atomically (copied next to the destination and renamed, across
  filesystems too). In-memory transforms use `BytesStep`; conversions use
  their own steps.
- Outputs with the input's extension use `infix_destination`
  (`NAME.<infix>.<ext>`); `suffix_destination` would overwrite the input.
- Commands that rewrite files in place refuse up front without `-y`
  (`require_overwrite`).
- `-o/--output` applies only when the inputs expand to exactly one file.
- The text tasks skip their own earlier outputs when walking a directory.

**Batches**

- Commands that report, rename or check without writing a file are plain
  functions run by `filejobs.batch.run_batch`.
- One policy for several inputs (`run_batch`, `run_jobs`, `finish_batch`):
  an input failing with one of `pipeline.JOB_ERRORS` is logged at ERROR when
  it happens and recorded, and the remaining inputs still run; any other
  exception is a bug and stops the command. If any input failed, `N done,
  M failed` goes to stderr and the exit status is 1.
- Commands that change files plan first, then apply. `-n/--dry-run` prints
  the plan, with paths shell-quoted, and runs nothing that writes (it may run
  read-only tools such as exiftool to build the plan).

**Output**

- Success is silent. stdout carries only what the command was asked for:
  reports, dry-run plans, generated text. Each written file is logged at
  INFO (`wrote <dest>`).
- Progress on a terminal: rich bars with `transient=True`, gone when the
  command ends. Elsewhere (pipe, cron, CI): the plain reporter logs INFO
  records on `filejobs.progress`, at most one per 10%.
- Every command takes `--log-level`/`-v`/`-q` after its name; the group takes
  none. `audio-grep` takes only `--log-level`, since grep owns `-v`/`-q`.
  They set up the `oddjob` logger with `foundation.loglib`
  (`ODDJOB_LOG_LEVEL` when no flag is given) and give the `filejobs` logger
  the same level; an explicit `--log-level` spec still decides per logger.
- Console output comes from `foundation.clilib.get_stderr_console()` /
  `RICH_STDERR_ENABLED`; modules log through `logging.getLogger(__name__)`.

## Consequences

- One place handles overwrite checks, temp-file cleanup, atomic landing and
  progress for every file-writing command.
- A failed input does not stop a large batch, but the command still fails, so
  scripts notice. A new error type that should count as an input failure is
  added to `JOB_ERRORS` instead of being caught locally.
- A successful run leaves nothing on screen. `-v` shows each written file
  and, off a terminal, the progress; `-n` shows each destination without
  running anything.
- Tests check written files through the filesystem and `assertLogs`, not
  stdout.

## Alternatives

- **Print `Wrote <dest>` per result**: explicit feedback, but against the
  silent-success convention, and progress stays noisy anyway.
- **Each command logs its own writes**: no shared logging setup, but the same
  line repeated in every command and the shared code's logs stay invisible.
- **`-q` also hides the rich bars**: transient bars leave nothing behind, so
  there is nothing to quiet once the run ends.
- **Logging flags before and after the command name**: possible by having
  the group record them and each command apply the merged level, but a
  second code path for one convenience.
