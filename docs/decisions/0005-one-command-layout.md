# 0005. One command layout for glados and multitool

Status: accepted (2026-11-06).

## Context

glados kept each task's steps and click command in one module,
`glados/tasks/<task>.py`. multitool separated domain modules from
`multitool/commands/<tool>.py`, as the general architecture rules ask
(entry points apart from core, no logic in command handlers). Two conventions
in one repository left the next command's location to guesswork.

## Decision

Both tools use the same layout:

- `<tool>/cli.py`: the click group only.
- `<tool>/commands/<command>.py`: one click command each. It parses options,
  expands inputs, wires adapters (glados: the backend, from `GladosContext`)
  and calls `run_jobs` or `run_batch`. No logic of its own.
- Domain modules hold steps, formatters, parsing and planning, with no CLI,
  and exist only where there is logic beyond wiring. For glados that is
  `glados/tasks/` (`protocols.py`, `transcribe.py`); the text tasks are one
  `TextStep` from core and have no domain module.
- click is imported only in `cli.py`, `commands/` and core's shared CLI
  plumbing (`core/cli_*.py`). `tests/test_boundaries.py` enforces this, and
  that multitool never imports `glados.commands`.

## Consequences

- One answer to where a command goes, checked by a test instead of review.
- glados' standalone scripts point at `glados.commands.<task>:cli`.
- A small task grows a domain module only when it gains logic of its own.

## Alternatives

- **Keep both conventions, documented**: no code change, but the rule
  depends on readers finding and following the documentation.
- **Split every glados task into steps and command**: one convention, but
  the text tasks would get modules holding only a constant.
