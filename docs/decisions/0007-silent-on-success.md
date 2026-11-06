# 0007. Silent on success: written files and progress go through logging

Status: accepted (2026-11-06). Partly supersedes 0004.

## Context

0004 made every command that writes a file print `Wrote <dest>` for each
result. That reverses the convention the tools are meant to follow: a
successful run prints nothing unless asked with `-v`. Two other things also
broke that convention, and 0004 did not cover either one:

- **Progress.** `filejobs.progress.create_reporter` draws rich bars when
  stderr is a terminal, and uses the plain reporter otherwise. The rich bars
  are not transient, so a finished batch leaves its overall bar on screen,
  and a single job leaves its step bars. The plain reporter `print`s
  `X: starting`, a line every 10% and `X: done` for every task (the batch
  and every step of every file). A cron or CI run over a directory writes
  hundreds of lines on success. Neither reporter follows `-v`/`-q`.
- **Verbosity scope.** `logging_options_for(app_logger)` applies
  `--log-level`/`-v`/`-q` to the app logger only (`glados` or `multitool`).
  The shared code logs under `filejobs.*`, which stays at the default
  `warning` level, so an INFO record from `filejobs` never shows, even with
  `-v`.

## Decision

- **Success is silent.** `run_jobs` and `run_single_job` log each written
  file at INFO (`wrote <dest>`, logger `filejobs.cli_options`) instead of
  printing `Wrote <dest>`. stdout carries only the output a command was
  asked for: dry-run plans and reports (`sidecars scan`, `img-hash`,
  `img-duplicates`, `motionphotos check`).
- **Failure is unchanged from 0004.** Each failing input is logged at ERROR
  when it happens, and the remaining inputs still run. At the end,
  `N done, M failed` goes to stderr, and the exit status is 1.
- **Progress on a terminal** uses rich bars with `transient=True`: they show
  while the command runs and are gone when it ends.
- **Progress elsewhere** (pipe, redirection, cron, CI): the plain reporter
  writes its lines as INFO records on `filejobs.progress` instead of
  printing them, with the same throttle (at most one line per 10%). It shows
  only with `-v`.
- **One verbosity for the whole tool.** `logging_options_for(app_logger)`
  gives the `filejobs` logger the app logger's level, so `-v`/`-q` and
  `<APP>_LOG_LEVEL` cover the shared code too. An explicit `--log-level`
  spec still decides per logger.

Everything else in 0004 stands: every file-producing command runs a `Job`;
reports, renames and checks run under `run_batch`; `JOB_ERRORS` defines an
input failure; `-o` needs exactly one input; the text tasks skip their own
outputs.

## Consequences

- A successful run prints nothing on a terminal once the bars clear, and
  nothing in a pipe or cron job. `-v` shows each written file and, off a
  terminal, the progress lines.
- Scripts that read `Wrote <dest>` from stdout break. They can use `-v` and
  read stderr, or compute the destination themselves. `-n` prints the
  destination of each input without running anything.
- A terminal run leaves no trace of what it did unless `-v` is given. That
  is the cost of the convention.
- Tests check written files through the filesystem and `assertLogs`, not
  stdout.

## Alternatives

- **Keep `Wrote <dest>` (0004 as it was):** explicit feedback, but against
  the convention, and progress stays noisy anyway.
- **Each command logs its own writes** under `glados.commands.*` or
  `multitool.commands.*`, which `-v` already covers: no change to the
  logging setup, but the same line repeated in every command, and the
  shared plumbing's own logs stay invisible.
- **`-q` also hides the rich bars on a terminal:** considered, not adopted.
  Transient bars leave nothing behind, so there is nothing to quiet once
  the run ends.
