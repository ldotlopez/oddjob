---
name: absorb-tool
description: Bring an outside tool (a script, an ocdutils leftover, a one-off utility) into this repository as a glados task (model/service-backed, with replaceable backends) or a multitool command (plain file utility), following decisions 0003-0006. Use whenever the user wants to port, absorb, migrate, add or "bring in" a tool, script or command to glados or multitool, asks where a new tool should go, or asks to add a new glados task or backend-backed command, even if they do not name this skill.
---

# Absorb a tool into glados / multitool

The repository has three packages and one way of doing things. Every new tool
must fit it without changing it:

- `filejobs/`: backend-free core shared by both tools (`Job`, steps,
  destination policies, `JOB_ERRORS`, `run_batch`, `run_jobs`, input
  expansion, shared click options, progress, ffmpeg runner). Imports neither
  tool.
- `glados/`: model-backed tasks. Task Protocol + backends in
  `glados/plugins/` declared through entry points + config.
- `multitool/`: file utilities with a single implementation, no backends,
  no config.

Same layout in both (0005): `<tool>/cli.py` is the group,
`<tool>/commands/<command>.py` is wiring only, domain modules have no CLI.
One batch policy (0004). `tests/test_boundaries.py` enforces imports and
where click may be imported.

A tool is **absorbed** when it runs as a `glados` task or a `multitool`
command, follows 0004's policies, has tests, and the docs describing it have
been proposed (and edited only after approval).

Before starting, read `README.md`, `docs/ARCHITECTURE.md` and
`docs/decisions/` (project rule), and check
`docs/plans/absorbing-tools.md` for open prerequisites and the inventory.

## Workflow

Port one tool per commit. Settle unclear points with the user before
writing code (one question at a time), never guess a classification.

### 1. Intake

Read the tool's source and fill its row in the inventory of
`docs/plans/absorbing-tools.md` (section 1):

| Column | Meaning |
|---|---|
| Writes files? | new file per input / rewrites in place / renames or moves / only reports |
| Replaceable implementation? | more than one plausible way (models, services, CLIs) the user would pick with `-b` |
| External binaries / services | what must be on PATH or reachable |
| New Python deps | each needs the user's approval under the dependency policy **before** porting |

### 2. Classify (first matching rule wins)

1. **Not absorbed**: interactive, a long-running service, machine- or
   account-specific; or a library needed outside this repo (→ `foundation`,
   propose it separately, never edit foundation from here).
2. **glados task**: the core operation goes through a model, remote
   service, or CLI with alternatives, even if only one backend exists today,
   as long as a second is plausible. Otherwise rule 3.
3. **multitool command**: deterministic file operation, one implementation.
   External programs are adapters, not backends.
4. **filejobs**: a generic piece moves there only once both tools need it
   (second consumer). Never imports `glados`/`multitool`; click only in
   `filejobs/cli_*.py`.

**Mixed tools** (model part + file part): prefer splitting along the model
boundary. The glados task writes a sidecar; a multitool command consumes
sidecars; the user composes them in the shell. If the split is unnatural the
whole tool is a glados task, and any multitool code it needs moves to
`filejobs` only if generic, else is rewritten in the task. Never copy
multitool modules into glados, never resolve a backend from multitool, never
import multitool from glados.

**Naming**: command names unique across both tools. glados tasks are also
standalone scripts, so no clash with common system commands. multitool
commands get no standalone script. Keep the source name unless it clashes or
misdescribes (precedent: `renamers` → `hash-rename`).

### 3. Pick the command shape (decision 0004)

| Shape | When | Runs through | Output |
|---|---|---|---|
| File producer | one input → one output file (new or in place) | `Job` + `run_jobs` (`job_action(job, overwrite)` or a custom action returning the written path) | `Wrote <dest>` per file, `N done, M failed`, exit 1 on failure |
| Single file | fixed explicit names (`join -i -v -o`) | `Job` + `run_single_job` | `Wrote <dest>`, clean `ClickException` on failure |
| Report / rename / check | no file produced | plain function per item + `run_batch` + `finish_batch` | own output, then the summary |

Rules for every shape:

- Inputs: `PATH...` via `paths_argument` + `expand_inputs(paths, accepts)`;
  the command picks the filter (`media_type_filter`,
  `text_inputs_except_outputs`, `accept_all`, or a domain filter).
- `-o/--output` only through `check_single_output`, wrapped with
  `override_destination`.
- Destinations: `suffix_destination` only when the output extension always
  differs from the input's; otherwise `infix_destination` (suffix would
  overwrite the input).
- `-y/--overwrite` (`overwrite_option`); in place needs `-y` unless in place
  by definition (`merge`).
- `-n/--dry-run` on every command that changes files: plan first, return
  before resolving any backend or external binary. Destination-only plan →
  `print_plan`; more than one action per item → frozen dataclasses with
  `describe()` (`Conversion`, `Merge`, `Rename`).
- Input failures are `JOB_ERRORS` (`OSError`, `RuntimeError`, `ValueError`,
  `SubprocessError`): raise one, don't catch locally. A genuinely new error
  class is added to `JOB_ERRORS` (and that is a decision record).
- Steps write temp files via `temp_output_path("<tool>-<step>-", suffix)`,
  never the destination; `Job` lands them atomically.
- Steps: `TextStep`, `BytesStep`, or a `ProgressStep[Path]` class yielding
  `ProgressEvent`s with a final `done=True` event carrying the temp path.

### 4. Port

- glados task or backend → follow `references/glados-task.md`.
- multitool command → follow `references/multitool-command.md`.

Read the existing command closest to the new one first (`rewrite.py` /
`transcribe.py` for glados; `conversions.py` / `motionphotos.py` /
`renames.py` for multitool) and match it.

### 5. Test

`uv run ruff check --fix . && uv run ruff format . && uv run python -m
unittest discover -s tests` must be green. Each tool needs:

- **Domain unit tests**: planning and pure logic (`test_multitool_domain.py`,
  or `test_<task>.py`).
- **Adapter/backend unit tests**: fake executables via
  `support.write_executable` (record argv, mimic output and failures) or
  `support.FakeHTTPServer`; never real services. glados backends are tested
  directly (options model, adapter, `__glados_plugin__`), not through the CLI.
- **CLI tests** with `CliRunner`: `-n` prints the plan with no backend
  configured and no binary; `Wrote <dest>`; exit 1 with `N done, M failed`
  when one input fails.
- **Integration**: `*IntegrationTest` classes. glados reads `GLADOS_TEST_*`
  from `tests/integration.env` (git-ignored, secrets: never print or commit
  it) and skips when unconfigured; multitool skips when a binary is missing
  from PATH; tests needing the extra skip without it.
- **Boundaries**: nothing to add; `test_boundaries.py` must stay green with
  no new exceptions.

### 6. Checklist before reporting done

- [ ] Inventory row filled; new dependencies approved and added with `uv add`.
- [ ] Classified; mixed tool split or justified.
- [ ] Shape chosen.
- [ ] Domain module (if needed), adapters, steps, command, registration.
- [ ] `-n` works with no backend and no binary; `-y` needed to overwrite;
      `-o` only with one input.
- [ ] Failures are `JOB_ERRORS`; batch continues; exit 1 + summary.
- [ ] Tests green; ruff clean.
- [ ] `pyproject.toml` (scripts, entry points, extra, description) + `uv sync`.
- [ ] Docs proposal made (step 7), nothing edited without a yes.

### 7. Propose documentation (never edit without explicit approval)

List the affected files with a one- or two-line summary each, then wait:

- `README.md`: the command, its options, runtime binaries.
- `docs/ARCHITECTURE.md`: module tree; a data-flow section if the tool adds
  a new kind of flow.
- `.claude/rules/glados.md`: implemented tasks list, runtime binaries, any
  new extra.
- `pyproject.toml` description: the tool list.
- `docs/decisions/`: a new record only if the port changes an approach
  (new command shape, new `JOB_ERRORS` member, code moved to `filejobs`, a
  tool that does not fit the classification). Decisions are append-only.
- `docs/plans/absorbing-tools.md`: mark the tool's inventory row done.
