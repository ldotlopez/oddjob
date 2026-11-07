# 0006. The backend-free core is its own package, filejobs

Status: accepted (2026-11-06). Partly supersedes 0003 and 0005. Partly superseded by 0011.

## Context

0003 split glados' core into a backend-free part, shared with multitool, and a
backend part, used only by glados, but kept both under `glados/core/`. So
`glados.core` meant two things, the next module's half was a guess, and
`tests/test_boundaries.py` guarded multitool with a list of forbidden glados
modules: a new glados-only core module was allowed for multitool by default.
The shared part also carried glados' name (`glados-` temp-file prefixes), and
`core/text_backend.py` imported `glados.tasks`.

## Decision

- The backend-free modules `pipeline`, `progress`, `runners`, `inputs`, `batch`
  and `cli_options` form a third top-level package, `filejobs`, in the same
  distribution. `glados.core` keeps only glados' backend part: `backends`,
  `config`, `cli_common`.
- `text_backend` moves to `glados/tasks/`: it adapts a transport to the task
  Protocols, so it is task code, not core.
- Imports (replaces 0003's "may import" / "must not import" lists):
  - `filejobs` imports neither `glados` nor `multitool`;
  - `multitool` imports nothing from `glados`;
  - `glados` never imports `multitool`.
- click may be imported in `cli.py`, `commands/` and the shared CLI plumbing,
  `filejobs/cli_*.py` and `glados/core/cli_*.py` (replaces 0005's
  `core/cli_*.py`).
- `tests/test_boundaries.py` checks all of it.

The rest of 0003 (one distribution, the `multitool` extra, no backends in
multitool) and of 0005 (the command layout) stands.

## Consequences

- The boundary is structural: a forbidden import is any import of the other
  tool, with no list to keep up to date.
- Moving the shared code to a uv workspace member or to `foundation` (0003's
  alternatives) is moving one directory.
- `filejobs` is still not published or versioned on its own; changing it can
  break either tool, and both tools' tests run together.
