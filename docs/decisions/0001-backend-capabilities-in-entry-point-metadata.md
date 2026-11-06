# 0001. Backend capabilities in entry-point metadata

Status: accepted (2026-11-06)

## Context

glados runs tasks (transcribe, rewrite, summarize, expand). Each task can be
done by one of several backends, and one backend can implement several tasks.
The app must know which backend implements which task **without loading the
backends**, to validate the `-b` switch, `GLADOS_<TASK>_BACKEND` and the config
`[tasks]` table, to pick a default and to give useful errors. Only the selected
backend is imported, and it gets its global options when it loads.

## Decision

The package metadata records which backend implements which task, as one
entry-point group per task in `pyproject.toml`:

```toml
[project.entry-points."glados.backends.transcribe"]
whisper = "glados.plugins.whisper:__glados_plugin__"
```

- `importlib.metadata.entry_points(group="glados.backends.<task>")` lists the
  implementors without importing anything (`core/backends.py:implementors`).
- Convention, checked as a string: the entry point's name is the backend name
  and its value is `glados.plugins.<name>:__glados_plugin__`. A mismatch is an
  error.
- Loading uses `foundation.plugin.Register(ns="glados.plugins",
  entry_point="__glados_plugin__")`. `register(name, options)` passes the
  merged global options to the entry point, which returns
  `(task name, task Protocol, object)` triples. `get_object(name, task,
  protocol)` returns the object and checks that it conforms to the protocol.
- The metadata is the index; foundation is the loader. The entry point's
  value is only checked, never `load()`ed.

## Consequences

- Adding a backend, or a task to a backend, means adding an entry-point line,
  and `uv sync` is needed for the installed metadata to change. Until then the
  app does not see the change.
- The metadata and the triples the entry point returns can disagree. A task
  that is listed but not returned fails when it is selected, with
  `ObjectNotFoundError`, reported as a backend error.
- A broken backend module (import error, missing optional dependency) is
  invisible until it is selected. It then fails with a clear error. No
  command fails because of a backend it does not use.
- Options of unused backends (`[backends.<name>]`) are not validated, because
  validating them needs the backend's options model, which means importing it.
  Their names are still checked against the metadata.

## Alternatives, and how to switch

- **Static map in core** (`BACKENDS = {"whisper": {"transcribe"}}`): no
  reinstall needed, but a second list to keep in sync. To switch, replace
  `implementors()` with a lookup in that map. Nothing else changes.
- **Import every module and read its declaration** (a top-level `TASKS`
  constant, or call each entry point): this is the import-everything approach
  of `plugin-subsystem-design.md`. It gives fail-fast detection of broken
  modules and allows validating every configured backend's options at startup,
  but every command pays for importing every backend, and a missing optional
  dependency breaks every command. To switch, build `implementors()` from
  `Register.discover()` plus the declarations.
- **Third-party backends outside `glados.plugins`**: drop the value
  convention and load with `EntryPoint.load()` instead of foundation's
  `Register`, then call the loaded function with the options.
