# Plan: merge multitool into glados, one tool

Status: proposed (2026-11-07).

## Context

The repository ships two command-line tools, `glados` (model-backed
tasks) and `multitool` (file utilities), split by an internal trait:
whether a command resolves a backend. Users have to know that trait to
find a command (`describe` is in glados, `img-caption` in multitool), and
the boundary blocks real work: describe+caption in one command needs
glados to import multitool's `CaptionStep`/`ExifTool`, which decision 0003
forbids.

The split no longer buys anything the code needs:

- It gives no dependency isolation: one distribution, one lockfile. Pillow
  is isolated by an optional extra and `load_extra_module`, not by the
  tree.
- "Has a backend" is now a per-command trait. A command takes
  `@pass_glados` (`glados/core/cli_common.py`) or it doesn't, and `Glados`
  (`glados/core/session.py`) loads config only on the first `config()`.
  A file command never reads config, so a broken `config.toml` cannot
  break `jpgize`, which is what the tree split used to guarantee.

Decisions taken with the user before this plan:

- `multitool` is dropped. Every command runs as `glados <command>`.
- All domain modules go into **one flat package**, `glados/lib/`, which
  replaces `glados/tasks/` and multitool's top-level modules.
- **No standalone scripts.** The 7 existing ones (`transcribe`, `rewrite`,
  `summarize`, `expand`, `translate`, `describe`, `audio-grep`) are
  removed; only `glados` stays on PATH.
- **Mixed commands are allowed.** A command may resolve a backend and do
  file work (e.g. describe+caption). This supersedes 0008's rule that
  mixed tools are split along the model boundary.

Defaults assumed here (cheap to change before applying):

- The package is named `glados/lib/`.
- The optional extra `multitool` becomes `images` (it holds Pillow and
  pillow-heif only).
- One logger, `glados`. `MULTITOOL_LOG_LEVEL` goes away in favour of
  `GLADOS_LOG_LEVEL`.
- `-v`/`-q`/`--log-level` stay per command (`glados transcribe -v`, as
  today), and the file commands gain them. Today they sit on multitool's
  group (`multitool -v jpgize`). The group itself takes no logging
  options.
- `filejobs/` stays a top-level package with its boundary unchanged.

Not in scope: the describe+caption command itself (item 3). It becomes
an ordinary command once this lands, in its own change.

## Target layout

```
glados/
  cli.py        one click group, every command, help panels by subject
  commands/     one module per command or command family (wiring only)
  core/         backends, config, session (Glados), cli_common: unchanged
  plugins/      backends: unchanged (imports glados.lib instead of glados.tasks)
  lib/          all domain modules: the 7 from glados/tasks/ and the 12
                from multitool/ (no name clashes, checked)
filejobs/       unchanged
```

`multitool/` and `glados/tasks/` are deleted.

## Boundaries after the merge (`tests/test_boundaries.py`)

1. `filejobs` imports no `glados` (unchanged in spirit).
2. `glados.lib` imports none of `glados.core`, `glados.plugins` or
   `glados.commands`: domain code knows nothing about config, backends
   or CLI. This holds today for `glados/tasks/` and for multitool, so the
   rule only makes it explicit.
3. `glados.plugins` imports only `glados.lib` (plus third-party), never
   `glados.core` or `glados.commands`. True today.
4. click only in `cli.py`, `commands/`, `filejobs/cli_*.py`,
   `glados/core/cli_*.py` (unchanged).
5. New behavioural test: a file command (`sidecars`, through the group)
   succeeds with a config loader that raises `ConfigError`. This proves
   that a command without `pass_glados` never touches config.

The tests for "multitool never imports glados" and "glados never imports
multitool" are deleted.

## Steps

Each step leaves `uv run python -m unittest discover -s tests` green and
ruff clean, and is its own commit.

### 1. Decision record (needs approval before editing)

`docs/decisions/0011-one-tool.md`:

- multitool merges into glados: one entry point, `glados`, no standalone
  scripts.
- Domain modules live in `glados/lib/`. The boundary is "domain code has
  no config, backends or CLI", not "which tool".
- A command needs config and backends only through `pass_glados`. A
  command that doesn't take it never loads config.
- Mixed commands are allowed. 0008's classification becomes "does it need
  a backend?" (task with Protocol and plugins, or plain command). Its rule
  1 (not absorbed) and its command shapes stay.
- Supersedes 0003. Partly supersedes 0005 (layout now for one tool), 0006
  (filejobs no longer "shared by two tools", but kept as the backend-free
  core) and 0008 (mixed-tools split, the naming rule on scripts).
- Status-line edits only: 0003 → `superseded by 0011`; 0005, 0006 and
  0008 gain `Partly superseded by 0011.`

### 2. Move the domain modules

- Use `git mv` for `glados/tasks/*.py` and `multitool/{captions,cleanup,
  conversions,dates,external,imgedit,imghash,media,motionphotos,renamers,
  shotwell,sidecars}.py` into `glados/lib/`.
- Rewrite the imports `glados.tasks.` → `glados.lib.` and `multitool.<mod>`
  → `glados.lib.<mod>` in `glados/`, `multitool/commands/` and `tests/`.
  `text_backend` is imported by the three text plugins, `protocols` by
  `whisper.py`, tests and commands.
- `load_extra_module` imports `glados.lib.{name}`, and its error message
  says `uv sync --extra images`.
- Temp-file prefixes `multitool-caption-`, `multitool-jpeg-` and
  `multitool-mp4-` become `glados-…`.
- `multitool/cli.py` still runs at this point, importing commands that now
  use `glados.lib`. Run the boundary tests' click rule. The
  "multitool/glados never import each other" tests are removed in this
  step, because `multitool/commands/` now imports `glados.lib`.

### 3. Move the commands into one group

- `git mv multitool/commands/*.py glados/commands/`. The names are
  `captions`, `cleanup`, `conversions`, `dates`, `imgedit`, `imghash`,
  `motionphotos`, `renames` and `sidecars`, and none clash with glados's.
- Each file command gains `@logging_options` (from
  `glados.core.cli_common`). Importing it loads no config.
- Rename the glados commands' `cli` objects to `<name>_cmd`
  (`transcribe_cmd`, …), matching the file commands. `cli` only meant
  "script entry point".
- `glados/cli.py` holds `TASK_COMMANDS` (backend commands, used by
  `tests/test_backends.py`) and `FILE_COMMANDS`. The group adds both and
  sorts them into rich-click `command_panel`s:
  - Text: `rewrite`, `summarize`, `expand`, `translate`, `describe`
  - Audio: `transcribe`, `audio-grep`
  - Images: `img-hash`, `img-duplicates`, `img-check`, `autocrop`,
    `img-reduce`, `img-caption`, `jpgize`
  - Media: `mp4ize`, `motionphotos`, `sidecars`, `date-sync`
  - Files: `hash-rename`, `fix-extensions`, `fs-cleanup`
- `command_panel` needs rich-click 1.9 (1.9.9 is installed), so run
  `uv add "rich-click>=1.9"`.
- The group's docstring describes the whole toolbox.
- Delete `multitool/` (only `cli.py` and `__init__.py` remain by now).
- `img-hash` cache: `UserCache(app="glados", base_dir=user_cache_dir("glados")
  / "imghash")`, next to audio-grep's `transcripts/`. Existing hashes under
  the `multitool` cache are recomputed once; nothing migrates them.

### 4. pyproject

- `[project.scripts]` keeps only `glados = "glados.cli:cli"`. The 7 task
  scripts and `multitool` go, along with the comment block about
  standalone tools.
- `[project.optional-dependencies]`: `multitool` → `images`.
- `[tool.setuptools.packages.find]` `include` drops `multitool*`, and the
  "two tools" comment is fixed.
- `description`: one sentence for one tool.
- `uv sync --extra images`.

### 5. Tests

- `git mv` `test_multitool_commands.py` → `test_file_commands.py`,
  `test_multitool_conversions.py` → `test_conversions.py`,
  `test_multitool_domain.py` → `test_file_domain.py`, and
  `test_multitool_integration.py` → `test_file_integration.py`.
- They invoke `glados.cli:cli` (or the command object) instead of
  `multitool.cli:cli`. Flags move from before the command name
  (`multitool -v jpgize`) to after it (`jpgize -v`). Logger resets use
  `("filejobs", "glados")`, and the domain test's `UserCache(app="multitool")`
  becomes `"glados"`.
- `test_boundaries.py`: `PACKAGES = ("filejobs", "glados")`, plus rules 2,
  3 and 5 above.
- `test_session.py` keeps `test_standalone_creates_a_glados`:
  `ensure_object` still matters for a command invoked on its own (tests,
  `python -m glados.commands.x`).

### 6. Docs (need approval before editing)

- `README.md`: one tool, `glados <command>`, no standalone scripts, the
  `images` extra, help panels; remove the multitool section.
- `docs/ARCHITECTURE.md`: the tree from "Target layout", the new
  boundaries, and the logging/env-var change.
- `.claude/rules/glados.md`: drop the multitool bullets and the
  "standalone script" sentence; `glados/tasks/` → `glados/lib/`; the new
  boundaries; `--extra images`.
- `.claude/skills/absorb-tool/`: the classification becomes "backend
  task" or "plain command" per 0011. `references/multitool-command.md` →
  `references/file-command.md`. Mixed tools may be one command.
- `docs/plans/multitool-integration.md` and `absorbing-tools.md` are
  historical and stay as they are.

## Risks

- **Muscle memory and scripts**: `multitool …`, `transcribe …` and the
  other bare task names stop working. Accepted (personal tool).
- **Log level env var**: `MULTITOOL_LOG_LEVEL` is ignored silently after
  the change. It's documented in the README update.
- **History**: `git mv` per file keeps `git log --follow`. Imports change in
  separate commits from moves where practical, so the renames are detected.
- **Help length**: 21 commands. The panels keep `glados --help` readable.
  Without them it's a flat wall.

## Verification

- Full suite green, ruff clean, after each step.
- `uv run glados --help` shows the five panels and 21 commands.
  `uv run multitool` and `uv run transcribe` no longer exist.
- `XDG_CONFIG_HOME=<dir with a broken config.toml> uv run glados sidecars
  <dir>` exits 0. The same config with `glados summarize` shows the config
  error box and exits 1, as today.
- `uv run glados img-hash` without the `images` extra prints the
  `uv sync --extra images` hint.
