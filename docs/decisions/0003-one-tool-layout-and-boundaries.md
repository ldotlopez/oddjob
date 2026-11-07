# 0003. One tool, one layout, checked import boundaries

Status: accepted (2026-11-07)

## Context

The project holds model-backed tasks and plain file utilities. They were
first two tools, split by whether a command resolves a backend. Users had to
know that internal trait to find a command, and the split blocked real work:
a command that describes an image and embeds the description needs both
halves. The two halves also had different module conventions, so where the
next command goes was a guess.

Two things still need protecting: domain code should not depend on config,
backends or click, and a command that needs no backend must not fail because
of a broken config.

## Decision

- **One tool**, `oddjob`: one click group holding every command, shown in
  help panels by subject. It is the only installed script; there are no
  standalone per-command scripts.
- **Layout**:
  - `oddjob/cli.py`: the click group and its help panels.
  - `oddjob/commands/<command>.py`: one click command or command family
    each, objects named `<name>_cmd`. Wiring only: parse options, expand
    inputs, wire adapters (for tasks, the backend from `Session`) and call
    `run_jobs` or `run_batch`.
  - `oddjob/lib/`: domain modules, flat (steps, formatters, parsing,
    planning, adapters for external programs), with no config, backends or
    CLI. A command gets one only when it has logic beyond wiring.
  - `oddjob/core/`: the backend part (`backends`, `config`, `session`,
    `cache`, `cli_common`, and helpers shared by commands that use backends).
  - `oddjob/plugins/`: backend modules only (0001).
  - `filejobs/`: a separate top-level package in the same distribution, the
    backend-free core (`pipeline`, `progress`, `runners`, `inputs`, `batch`,
    `cli_options`).
- **Boundaries**, checked by `tests/test_boundaries.py`:
  - `filejobs` imports nothing from `oddjob`;
  - `oddjob.lib` imports none of `oddjob.core`, `oddjob.plugins`,
    `oddjob.commands`;
  - `oddjob.plugins` imports only `oddjob.lib`;
  - click (and rich-click) only in `cli.py`, `commands/`,
    `filejobs/cli_*.py` and `oddjob/core/cli_*.py`.
- **Config and backends only through `pass_session`.** A command that does
  not take it never loads config; `tests/test_session.py` runs one with a
  config loader that always fails.
- A command may resolve a backend and do file work in one run (a mixed
  command).
- Pillow-based code needs the optional extra `images` (Pillow,
  pillow-heif); commands load those modules through `load_extra_module`.

## Consequences

- One place to look for a command; `oddjob --help` lists all of them.
- A composed command (describe and embed, for one) is an ordinary command,
  with no import exception.
- The boundaries are structural and tested, not a convention left to
  review.
- `filejobs` is not versioned on its own; changing it can break any command,
  and every test runs together. Moving it to a uv workspace member or to
  `foundation` is moving one directory.
- A flat `oddjob/lib/` can be split into subject packages later if it grows.

## Alternatives

- **Two tools with an import exception for mixed commands**: keeps the split
  along an implementation detail, and every mixed command needs its own
  exception.
- **A `ToolWithBackend` base class**: a class hierarchy for what
  `pass_session` and `Session.backend` already do by composition.
- **Domain modules in subject packages** (`oddjob/text/`, `oddjob/images/`):
  closer to what commands do, but more churn with no name clashes to solve.
- **uv workspace** (shared core and the tool as separate members): makes the
  `filejobs` boundary checkable by environment, at the cost of a repository
  restructure and a real `[build-system]` per member. Worth it only if
  `filejobs` gets a second consumer outside this repository; for code needed
  outside, prefer `foundation`.
