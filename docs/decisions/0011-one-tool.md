# 0011. One tool: multitool merges into glados

Status: accepted (2026-11-07). Supersedes 0003. Partly supersedes 0005,
0006 and 0008.

## Context

0003 made the file utilities a second tool, `multitool`, beside glados,
split by one internal trait: whether a command resolves a backend. Users
had to know that trait to find a command (`glados describe`, but
`multitool img-caption`), and the boundary blocked real work: a command
that describes images and writes the caption needs glados to import
multitool's caption code, which 0003 and 0006 forbid. 0008 worked around
it by splitting such tools in two and leaving the composition to the
shell.

The split no longer protects anything. Both tools ship in one
distribution with one lockfile; Pillow is isolated by an optional extra
and `load_extra_module`, not by the tree. Whether a command needs a
backend is now a per-command trait: it takes `pass_glados`
(`core/cli_common.py`) or it doesn't, and `Glados` (`core/session.py`)
loads config only on the first `config()`. A file command never reads
config, so a broken config cannot break it, which is what the tree split
used to guarantee.

## Decision

- One tool, `glados`, with one click group holding every command, shown
  in help panels by subject (Text, Audio, Images, Media, Files). The
  `multitool` entry point is removed.
- No standalone scripts: only `glados` is installed. The task scripts
  (`transcribe`, `rewrite`, …) are removed. Command objects are named
  `<name>_cmd`.
- Domain modules, the task code that was `glados/tasks/` and multitool's
  file code alike, live in one flat package, `glados/lib/`. `multitool/`
  and `glados/tasks/` are gone.
- Boundaries, checked by `tests/test_boundaries.py`:
  - `filejobs` imports nothing from `glados`;
  - `glados.lib` imports none of `glados.core`, `glados.plugins` and
    `glados.commands`: domain code has no config, backends or CLI;
  - `glados.plugins` imports `glados.lib` only, never `glados.core` or
    `glados.commands`;
  - click only in `cli.py`, `commands/`, `filejobs/cli_*.py` and
    `glados/core/cli_*.py`, as before.
- A command reaches config and backends only through `pass_glados`. A
  command that doesn't take it never loads config;
  `tests/test_session.py` runs one with a config loader that always
  fails.
- A command may resolve a backend and do file work in one run (a mixed
  command). This replaces 0008's rule that mixed tools are split along the
  model boundary. 0008's classification becomes: a tool whose core
  operation goes through a model, a remote service or a CLI with
  alternatives is a **task** (Protocol, backends in `glados/plugins/`, an
  entry-point group, config); anything else is a **plain command**. 0008's
  rule 1 (what is not absorbed), its command shapes and its naming rule
  (unique command names, source names kept) stand; its rule about
  standalone scripts does not.
- Every command takes `--log-level`/`-v`/`-q` after its name (`glados
  jpgize -v`); the group takes none. `audio-grep` takes only
  `--log-level`, since grep owns `-v`/`-q`. One logger, `glados`
  (`GLADOS_LOG_LEVEL`).
- The optional extra `multitool` is renamed `images` (Pillow,
  pillow-heif).
- `filejobs` stays a separate top-level package: the backend-free,
  click-free (outside `cli_*`) core, as 0006 decided.

## Consequences

- One place to look for a command, and `glados --help` lists all of them.
- A composed command (describe and caption, for one) is an ordinary
  command, with no import exception.
- Breaking for users: `multitool <command>` and the bare task scripts stop
  working, `MULTITOOL_LOG_LEVEL` is ignored, log flags move after the
  command name, `--extra multitool` becomes `--extra images`, and
  `motionphotos join`/`split` take `--video` only (its `-v` alias would
  clash with verbose).
- img-hash's cache moves under glados' cache directory (`imghash/`);
  hashes cached by multitool are recomputed once.
- "task" keeps its meaning: a command with backends, listed by its
  `glados.backends.<task>` entry-point group (`core.backends.tasks()`).
  Not every command is a task.

## Alternatives

- **Keep two tools, add an import exception for mixed commands**: no
  break for users, but the boundary stays split along an implementation
  detail, and every mixed tool would need its own exception.
- **A `ToolWithBackend` base class for backend commands**: rejected; it
  brings back a class hierarchy for what `pass_glados` and
  `Glados.backend` already do by composition.
- **Domain modules in subject packages** (`glados/text/`,
  `glados/images/`, …): closer to what commands do, but more churn for
  19 modules with no name clashes; a flat `glados/lib/` can be split
  later if it grows.
- **Logging flags accepted before and after the command**: possible by
  having the group record them and each command apply the merged level,
  but it adds a second code path for one convenience.
