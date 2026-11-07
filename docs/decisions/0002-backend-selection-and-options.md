# 0002. Backend selection and options

Status: accepted (2026-11-07)

## Context

With several backends per task (0001), each run has to settle which backend
runs a task and with which options. A backend's options apply to every task
it runs, but tasks need different settings from the same backend: `describe`
needs a vision model, while a small model is enough for `translate`. A run
that uses two tasks on one backend has no per-run flag to tell them apart.

## Decision

- **Selection**, per task, first match wins: `-b`, then
  `ODDJOB_<TASK>_BACKEND`, then `[tasks]` in the config, then the only
  installed implementor. With several implementors and none chosen, the
  command fails and names the three ways to choose.
- **Options**, lowest first: the backend's defaults, `[backends.<name>]`
  without its `tasks` table, `[backends.<name>.tasks.<task>]`, then CLI
  overrides (`-m` → `model`). `Config.backend_options(backend, task)` merges
  them and `core.backends.resolve` applies them.

  ```toml
  [backends.openai]
  model = "gpt-5-mini"

  [backends.openai.tasks.describe]
  model = "gpt-5"
  ```

- `tasks` is a reserved key in a backend table: no backend may have an option
  named `tasks`. A per-task table never selects a backend; it applies only
  when its backend is the selected one.
- The config check (`check_config`) rejects unknown backends, unknown tasks,
  and per-task tables for a task the backend does not implement. Option
  values are validated only when the backend loads, by its own model.
- Per-run values (input text, language, prompt) are method arguments, not
  options.
- Prompts live in the config's `[prompts]`, owned by the tasks, never in a
  backend.
- The config is optional: `$XDG_CONFIG_HOME/oddjob/config.toml`, with `${VAR}`
  expanded and `.env` loaded. `Session` (`core/session.py`) reads it on first
  use, never at import. `Session.backend_options` resolves a task's backend
  name and effective options without loading the backend.

## Consequences

- Options stay tied to the backend they belong to, so `-b` never applies
  options meant for another backend.
- A backend may get different options per task, so it is built once per task
  that uses it (`resolve` builds on every call).
- An invalid option in a per-task table is reported against
  `backends.<name>`, without naming the per-task table it came from.
- With two transcribe backends installed (`whisper`, `whisper_cpp`), there is
  no default: the user picks one.

## Alternatives

- **A table under `[tasks]`** (`[tasks.describe]` with `backend` plus
  options): selection and options in one place, but ambiguous when `-b`
  picks another backend with a different option set; the options would have
  to be dropped silently or rejected.
- **Task-wide options regardless of backend** (`[task_options.describe]`):
  wrong for the same reason; a whisper.cpp model path is not an OpenAI model
  name.
