# 0002. One plugin module may provide several backends

Status: accepted (2026-11-06). Supersedes 0001.

## Context

Decision 0001 records which backend implements which task in entry-point
metadata, and ties each backend to a module of the same name
(`glados.plugins.<name>:__glados_plugin__`). Some backends are close variants
of one another: OpenAI's `whisper` CLI and whisper.cpp's `whisper-cli` share
the flow (audio in, JSON out, progress on stderr) and the runner, and differ
only in flags, model semantics, JSON layout and progress format. Forcing them
into two modules duplicates that shared code. Folding them into one backend
with an `engine` option would mix two option sets (a model name vs. a ggml
path) under one config table.

## Decision

Everything in 0001 stands, except the one-module-per-backend rule:

- The entry point's name is the backend name; its value must match
  `glados.plugins.<module>:__glados_plugin__`, where `<module>` is any module
  in `glados.plugins`. Several entry points may name the same module:

  ```toml
  [project.entry-points."glados.backends.transcribe"]
  whisper = "glados.plugins.whisper:__glados_plugin__"
  whisper_cpp = "glados.plugins.whisper:__glados_plugin__"
  ```

- The entry point receives the selected backend's name as well as its
  options: `__glados_plugin__(backend, options)`. It builds only that
  backend, validating only its options, and returns its
  `(task name, task Protocol, object)` triples. Inside the module the choice
  is a name → factory mapping, the module's composition point.
- `core/backends.py` maps backend → module from the metadata and registers
  the module with foundation's `Register`, keyed by module, passing the
  backend name and options. A backend name must map to the same module in
  every task group; otherwise the config check fails.
- Options stay per backend: `[backends.whisper]` and `[backends.whisper_cpp]`
  are separate tables, validated by separate models.

## Consequences

- Variants of one tool share code in one module with no cross-module
  imports, and each keeps its own clean options model.
- Every `__glados_plugin__` takes the backend name, even in a module that
  provides a single backend; such a module may ignore it or check it.
- Renaming applied with this decision: the whisper.cpp backend is now
  `whisper_cpp`, and `whisper` is OpenAI's CLI. Existing `-b whisper`,
  `[tasks] transcribe = "whisper"` and `[backends.whisper]` settings now
  select OpenAI's CLI; a ggml `model` path there fails when transcribing.
- With two transcribe backends installed, glados no longer picks one by
  default: pass `-b`, set `GLADOS_TRANSCRIBE_BACKEND` or `[tasks] transcribe`.
- foundation's `Register` keys by module, so one `Register` can hold only one
  backend per module. `load()` builds a fresh `Register` per call, so this
  does not matter today.

## Alternatives, and how to switch

- **0001 as it was** (one module per backend): move each backend of a
  multi-backend module into its own `glados.plugins.<name>` module, drop the
  `backend` argument from `__glados_plugin__`, and restore the
  `value == glados.plugins.<name>:...` check in `_modules()`.
- **One backend with an engine option**: a single `whisper` backend whose
  `engine` option picks the implementation. One config table, but option
  types and defaults then depend on another option's value.
