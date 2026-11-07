# 0010. Per-task backend options, nested in the backend's table

Status: accepted (2026-11-07).

## Context

A backend's options (`[backends.<name>]`) apply to every task it runs. One
`openai` table therefore gives `describe`, which needs a vision model, and
`translate`, where a small model is enough, the same `model`. Single-task
commands work around it with `-m`, but config alone cannot say "this
backend, with this model, for this task", and a run that uses two tasks on
one backend (a composed tool through `Glados`, `core/session.py`) has no
per-run flag to fall back on.

## Decision

- A backend's table may hold a `tasks` table with one table per task:

  ```toml
  [backends.openai]
  model = "gpt-5-mini"

  [backends.openai.tasks.describe]
  model = "gpt-5"
  ```

- Options for a backend running a task are, lowest first: the backend's
  defaults, `[backends.<name>]` without its `tasks` table,
  `[backends.<name>.tasks.<task>]`, then CLI overrides (`-m` → `model`).
  `Config.backend_options(backend, task)` does the merge and
  `core.backends.resolve` applies it.
- `tasks` is a reserved key in a backend table: no backend may name an
  option `tasks`.
- The config check (`check_config`) rejects a per-task table for an unknown
  task, or for a task the backend does not implement. Option values are
  still validated only when the backend loads, by its own model, as before.
- Which backend runs a task is unchanged: `-b`, `GLADOS_<TASK>_BACKEND`,
  `[tasks]`, the only implementor. A per-task table never selects a
  backend; it applies only when its backend is the selected one.

## Consequences

- Existing configs keep working unchanged.
- Options stay tied to the backend they belong to, so switching a task's
  backend with `-b` never applies options meant for another backend.
- A backend may be built with different options per task, so it is built
  once per task that uses it (as `resolve` already does on every call).
- An invalid option in a per-task table is reported against
  `backends.<name>`, without naming the per-task table it came from.

## Alternatives

- **A table under `[tasks]`** (`[tasks.describe]` with `backend` plus
  options): selection and options in one place, but ambiguous when `-b`
  picks another backend, whose option set differs: the options would have
  to be dropped silently or rejected.
- **Task-wide options regardless of backend** (`[task_options.describe]`):
  wrong for the same reason; a whisper.cpp model path is not an OpenAI
  model name.
