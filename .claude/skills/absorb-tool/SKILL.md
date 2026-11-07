---
name: absorb-tool
description: Bring an outside tool (a script, an ocdutils leftover, a one-off utility) into this repository as an oddjob command, either a task (model/service-backed, with replaceable backends) or a plain file command, following decisions 0003-0005. Use whenever the user wants to port, absorb, migrate or "bring in" an existing tool, script or command to oddjob, or asks where such a tool should go, even if they do not name this skill. Its classification, command shapes, test and docs rules are also the conventions the create-tool skill follows; for a new tool designed from scratch (no source to port), use create-tool instead.
---

# Absorb a tool into oddjob

The repository is one tool, `oddjob` (decision 0003), in two packages, with
one way of doing things. Every new tool must fit it without changing it:

- `filejobs/`: backend-free core (`Job`, steps, destination policies,
  `JOB_ERRORS`, `run_batch`, `run_jobs`, input expansion, shared click
  options, progress, ffmpeg runner). Imports nothing from `oddjob`.
- `oddjob/`: `cli.py` is the one group (help panels by subject),
  `commands/<command>.py` is wiring only, `lib/` holds the domain modules
  (no config, backends or CLI), `core/` the backend machinery, `plugins/`
  the backends. Commands are **tasks** (task Protocol + backends in
  `oddjob/plugins/` declared through entry points + config, reached through
  `pass_session`) or **plain file commands** (one implementation, no
  backends, never `pass_session`).

One batch policy (0004). `tests/test_boundaries.py` enforces imports and
where click may be imported.

A tool is **absorbed** when it runs as an `oddjob` command, follows 0004's
policies, has tests, and the docs describing it have been proposed (and
edited only after approval).

Before starting, read `README.md`, `docs/ARCHITECTURE.md` and
`docs/decisions/` (project rule). Decision 0005 lists the tools already
left out and why; `docs/BACKLOG.md` lists open work that may touch the
tool being ported.

## Workflow

Port one tool per commit. Settle unclear points with the user before
writing code (one question at a time), never guess a classification.

### 1. Intake

Read the tool's source and settle these points with the user:

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
2. **Task**: the core operation goes through a model, remote
   service, or CLI with alternatives, even if only one backend exists today,
   as long as a second is plausible. Otherwise rule 3.
3. **Plain file command**: deterministic file operation, one implementation.
   External programs are adapters, not backends.
4. **filejobs**: a generic piece moves there only once it is not oddjob-
   specific and a second consumer needs it. Never imports `oddjob`; click
   only in `filejobs/cli_*.py`.

**Mixed tools** (model part + file part, decision 0003): one command may do
both. It takes `pass_session` and resolves the backend for its model part,
and reuses the domain code in `oddjob/lib/` for the file part (e.g. a
describe step followed by `CaptionStep`). The model part still gets a task
(Protocol, entry-point group, backends), so its backend is replaceable.
Split it into two commands only when each half is useful on its own.

**Naming**: command names are unique. Only `oddjob` is installed, so
commands get no standalone script. Keep the source name unless it clashes or
misdescribes (precedent: `renamers` → `rename-by-hash`).

### 3. Pick the command shape (decision 0004)

| Shape | When | Runs through | Output |
|---|---|---|---|
| File producer | one input → one output file (new or in place) | `Job` + `run_jobs` (`job_action(job, overwrite)` or a custom action returning the written path) | nothing on success (`wrote <dest>` at INFO, shown with `-v`); on failure `N done, M failed` on stderr, exit 1 |
| Single file | fixed explicit names (`join -i --video -o`) | `Job` + `run_single_job` | nothing on success (`wrote <dest>` at INFO); clean `ClickException` on failure |
| Report / rename / check | no file produced | plain function per item + `run_batch` + `finish_batch` | the report on stdout (what the command is for); summary on failure |

Silent on success (decision 0004): stdout carries only what the command was
asked for (reports, `-n` plans), never confirmations. Use `LOGGER.info` for
anything else; never `click.echo` a success message. Progress needs nothing
from the command: rich bars are transient, and off a terminal progress is
INFO logging.

Rules for every shape:

- Inputs: `PATH...` via `paths_argument` + `expand_inputs(paths, accepts)`;
  the command picks the filter (`media_type_filter`,
  `text_inputs_except_outputs`, `accept_all`, or a domain filter).
- `-o/--output` only through `check_single_output`, wrapped with
  `override_destination`.
- Destinations: `suffix_destination` only when the output extension always
  differs from the input's; otherwise `infix_destination` (suffix would
  overwrite the input).
- `-y/--overwrite` (`overwrite_option`); writing in place always needs `-y`,
  checked up front with `require_overwrite` (skipped under `-n`).
- `-n/--dry-run` on every command that changes files: plan first, run
  nothing that writes. Read-only tools the plan needs may run (`date-copy
  --from exif -n` reads with exiftool); return before resolving anything
  only the writes need. Destination-only plan → `print_plan`; more than one
  action per item → frozen dataclasses with `describe()` (`Conversion`,
  `Merge`, `Rename`), paths quoted with `shlex` (`shlex.join` for
  shell-like lines).
- Input failures are `JOB_ERRORS` (`OSError`, `RuntimeError`, `ValueError`,
  `SubprocessError`): raise one, don't catch locally. A genuinely new error
  class is added to `JOB_ERRORS` (and that is a decision record).
- Steps write temp files via `temp_output_path("<tool>-<step>-", suffix)`,
  never the destination; `Job` lands them atomically.
- Steps: `TextStep`, `BytesStep`, or a `ProgressStep[Path]` class yielding
  `ProgressEvent`s with a final `done=True` event carrying the temp path.

### 4. Port

- Task or backend → follow `references/oddjob-task.md`.
- Plain file command → follow `references/file-command.md`.
- Mixed command → both: the task part from `oddjob-task.md`, the file part
  from `file-command.md`.

Read the existing command closest to the new one first (`rewrite.py` /
`transcribe.py` for tasks; `conversions.py` / `motionphotos.py` /
`renames.py` for file commands) and match it.

### 5. Test

`uv run ruff check --fix . && uv run ruff format . && uv run python -m
unittest discover -s tests` must be green. Each tool needs:

- **Domain unit tests**: planning and pure logic (`test_file_domain.py`,
  or `test_<task>.py`).
- **Adapter/backend unit tests**: fake executables via
  `support.write_executable` (record argv, mimic output and failures) or
  `support.FakeHTTPServer`; never real services. oddjob backends are tested
  directly (options model, adapter, `__oddjob_plugin__`), not through the CLI.
- **CLI tests** with `CliRunner`: `-n` prints the plan with no backend
  configured and no binary; on success empty stdout and a `wrote <dest>`
  record (`assertLogs("filejobs", "INFO")`); exit 1 with `N done, M failed`
  when one input fails.
- **Integration**: `*IntegrationTest` classes. oddjob reads `ODDJOB_TEST_*`
  from `tests/integration.env` (git-ignored, secrets: never print or commit
  it) and skips when unconfigured; file commands skip when a binary is missing
  from PATH; tests needing the extra skip without it.
- **Boundaries**: nothing to add; `test_boundaries.py` must stay green with
  no new exceptions.

### 6. Checklist before reporting done

- [ ] Inventory row filled; new dependencies approved and added with `uv add`.
- [ ] Classified; a mixed tool is one command, or split with a reason.
- [ ] Shape chosen.
- [ ] Domain module (if needed), adapters, steps, command, registration.
- [ ] `-n` works with no backend and no binary; `-y` needed to overwrite;
      `-o` only with one input.
- [ ] Failures are `JOB_ERRORS`; batch continues; exit 1 + summary.
- [ ] Tests green; ruff clean.
- [ ] `pyproject.toml` (entry points, extra, description) + `uv sync`.
- [ ] Docs proposal made (step 7), nothing edited without a yes.

### 7. Propose documentation (never edit without explicit approval)

List the affected files with a one- or two-line summary each, then wait:

- `README.md`: the command, its options, runtime binaries.
- `docs/ARCHITECTURE.md`: module tree; a data-flow section if the tool adds
  a new kind of flow.
- `.claude/rules/oddjob.md`: implemented tasks or file commands list,
  runtime binaries, any new extra.
- `pyproject.toml` description: the tool list.
- `docs/decisions/`: a new record only if the port changes an approach
  (new command shape, new `JOB_ERRORS` member, code moved to `filejobs`, a
  tool that does not fit the classification, a tool left out for a reason
  decision 0005 does not already give). Decisions are append-only.
