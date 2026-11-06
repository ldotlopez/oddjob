# 0004. Every command that produces a file runs a Job; batches continue past failures

Status: accepted (2026-11-06).

## Context

glados' tasks and multitool's utilities both take `PATH...` and act on every
file it expands to. Before this decision multitool wrote files in several ways
(direct writes, `shutil.move`, in-place rewrites), and what happened when one
of many inputs failed differed per command. glados already had `Job`: steps
write temp files, and the last one lands at the destination after a
destination check.

## Decision

- Every command that produces a file runs a `core.pipeline.Job`, so all
  results land the same way: temp file, destination re-checked (`-y` to
  replace), then an atomic rename (copy next to the destination and rename
  across filesystems). In-memory transforms use `BytesStep`; conversions use
  their own steps.
- Commands that report, rename or check without producing a file are plain
  functions run by `core.batch.run_batch`. They do not need a `Job`.
- Several inputs, one policy (`run_batch`, `finish_batch`, `run_jobs`):
  - an input failing with one of `pipeline.JOB_ERRORS` is logged when it
    happens and recorded, and the remaining inputs still run;
  - any other exception is a bug and stops the command;
  - at the end, `N done, M failed` is printed and the exit status is 1 if any
    input failed;
  - commands that write files print `Wrote <dest>` for each result.
- `-o/--output` applies only when the inputs expand to exactly one file.
- The text tasks skip their own earlier outputs (`<name>.<infix>.<ext>`) when
  walking a directory.

## Consequences

- One place handles overwrite checks, temp-file cleanup, atomic landing and
  progress for every file-producing command of both tools.
- A failed input does not stop a large batch, but the command still fails, so
  scripts notice.
- A new error type that should count as an input failure has to be added to
  `JOB_ERRORS` (or raised as one of its members) instead of caught locally.
