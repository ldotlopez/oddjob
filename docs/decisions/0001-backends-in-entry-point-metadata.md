# 0001. Backends are declared in entry-point metadata

Status: accepted (2026-11-07)

## Context

oddjob's tasks (transcribe, speak, rewrite, summarize, expand, translate,
describe) can each be done by several backends, and one backend can implement
several tasks. oddjob must know which backend implements which task **without
importing any backend**: to validate `-b`, `ODDJOB_<TASK>_BACKEND` and the
config's `[tasks]`, to pick a default, and to give useful errors. Only the
selected backend is imported.

Some backends are close variants of one another: OpenAI's `whisper` CLI and
whisper.cpp's `whisper-cli` share the flow (audio in, JSON out, progress on
stderr) and the runner, and differ only in flags, model semantics, JSON
layout and progress format.

## Decision

- The package metadata says which backend implements which task: one
  entry-point group per task in `pyproject.toml`, `oddjob.backends.<task>`.

  ```toml
  [project.entry-points."oddjob.backends.transcribe"]
  whisper = "oddjob.plugins.whisper:__oddjob_plugin__"
  whisper_cpp = "oddjob.plugins.whisper:__oddjob_plugin__"
  ```

- The set of these groups is the task list (`core.backends.tasks()`). A new
  task needs its group and nothing else; no other code lists tasks.
- The entry point's name is the backend name. Its value must be
  `oddjob.plugins.<module>:__oddjob_plugin__`, checked as a string and never
  `load()`ed. Several backends may name the same module; a backend must name
  the same module in every group, or the config check fails.
- `importlib.metadata.entry_points` lists the implementors without importing
  anything.
- Loading goes through `foundation.plugin.Register(ns="oddjob.plugins",
  entry_point="__oddjob_plugin__")`, keyed by module, and only for the
  selected backend. `__oddjob_plugin__(backend, options)` builds only the
  named backend, validates its options with that backend's own pydantic model
  (`extra="forbid"`, a default for every field), and returns
  `(task name, task Protocol, object)` triples. `get_object` checks that the
  object conforms to the Protocol. Inside a module the choice is a name →
  factory mapping, the module's composition point.
- Options are per backend: `[backends.whisper]` and `[backends.whisper_cpp]`
  are separate tables, validated by separate models.
- `oddjob/plugins/` holds backend modules only.

## Consequences

- Adding a backend, or a task to a backend, is an entry-point line plus
  `uv sync`; until then the installed metadata does not show it.
- The metadata and the returned triples can disagree. A task that is listed
  but not returned fails when selected (`ObjectNotFoundError`, reported as a
  backend error).
- A broken backend module (import error, missing optional dependency) is
  invisible until selected, and then fails with a clear error. No command
  fails because of a backend it does not use.
- Options of unused backends are not validated: that needs the backend's
  options model, which means importing it. Their names are still checked
  against the metadata.
- Variants of one tool share code in one module, each with its own clean
  options model. Every `__oddjob_plugin__` takes the backend name, even in a
  module with a single backend.
- foundation's `Register` keys by module, so one `Register` holds one backend
  per module. `load()` builds a fresh `Register` per call, so this does not
  matter today.
- This registry is a deliberate exception to the general rule against plugin
  registries: backends are the replaceable part of this project.

## Alternatives

- **Static map in core** (`BACKENDS = {"whisper": {"transcribe"}}`): no
  reinstall needed, but a second list to keep in sync.
- **Import every module and read its declaration**: fail-fast detection of
  broken modules and validation of every configured backend's options, but
  every command pays for importing every backend, and one missing optional
  dependency breaks every command.
- **One module per backend**: simpler naming, but variants such as whisper
  and whisper.cpp duplicate their shared code or import across modules.
- **One backend with an `engine` option**: one config table, but option
  types and defaults then depend on another option's value.
- **Third-party backends outside `oddjob.plugins`**: drop the value
  convention and load with `EntryPoint.load()` instead of `Register`.
  Not needed while every backend lives in this repository.
