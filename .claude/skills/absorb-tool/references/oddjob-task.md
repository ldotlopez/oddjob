# Porting an oddjob task (or adding a backend)

A new backend for an existing task needs only steps 6–7 and its tests.
A new task needs everything, in this order.

1. **Contract**: add a `Protocol` to `oddjob/lib/protocols.py`
   (`@runtime_checkable`). Per-run values are keyword method arguments;
   backend settings are options. Return a `ProgressStream[T]` whose final
   event (`done=True`) carries the result.

2. **Domain**: add `oddjob/lib/<task>.py` only if the task has logic
   beyond wiring (steps, formatters, parsing), like `transcribe.py`
   (`AudioExtractor`, `TranscribeStep`, `FORMATTERS`). A task that is a
   single `TextStep` has no domain module.

3. **Task registry**: nothing to add. The task list is the set of
   `oddjob.backends.<task>` entry-point groups (`core.backends.tasks()`), so
   the group added in step 7 registers the task; the config check rejects
   unknown `[tasks]` keys.

4. **Prompts (text tasks only)**: add a field and a `render_<task>()`
   method to `Prompts` in `oddjob/core/config.py`, with its placeholder
   validated like the existing ones (`_check_placeholders`). Prompts belong
   to the task, never to a backend.

5. **Text backends (text tasks only)**: add the method to
   `oddjob/lib/text_backend.TextBackend` and the triple to
   `text_plugin_triples()`. `openai`, `ollama` and `llm` then implement the
   task with no plugin change.

6. **Backend (non-text task, or a new service)**:
   `oddjob/plugins/<module>.py`, which holds only plugin code:
   - a pydantic options model, `extra="forbid"`, defaults for everything;
   - the adapter class: thin, does the I/O, reports progress as a
     `ProgressStream`. Subprocess CLIs: long options only when the CLI
     ignores unknown flags (see the `whisper-cli` note in
     `.claude/rules/oddjob.md`);
   - `__oddjob_plugin__(backend, options)`: builds only the named backend
     (name → factory mapping), validates only its options, returns
     `(task, Protocol, object)` triples, one per task. One module may hold
     several variants (decision 0002).
   Model defaults go through `platformdirs`; no env lookups or hardcoded
   paths elsewhere.

7. **Entry points**: in `pyproject.toml`,
   `[project.entry-points."oddjob.backends.<task>"]` with
   `<backend> = "oddjob.plugins.<module>:__oddjob_plugin__"`. A backend names
   the same module in every group. Run `uv sync`.

8. **Command**: `oddjob/commands/<task>.py`, object `<task>_cmd`, decorator stack as in
   `oddjob/commands/rewrite.py`:
   `@click.command("<task>")`, `@paths_argument`, task options,
   `@model_option`, `@backend_option("<task>")`, `@common_file_options`,
   `@dry_run_option`, `@logging_options`, `@pass_session`.
   Body, in order:
   1. `inputs = expand_inputs(paths, <filter>)`
   2. `check_single_output(output, inputs)`
   3. `dest_fn = override_destination(output, <suffix|infix>_destination(...))`
   4. `if dry_run: print_plan(inputs, dest_fn); return`
   5. render the prompt (text tasks), then
      `oddjob.backend("<task>", <Protocol>, backend, {"model": model})`
   6. build the `Job` and `run_jobs(inputs, job_action(job, overwrite), "<Verb>ing")`
   No logic beyond this wiring; anything more belongs in step 2.

9. **Registration**: add the command to `TASK_COMMANDS` and to a panel of
   `PANELS` in `oddjob/cli.py`. No `[project.scripts]` entry: only `oddjob`
   is installed.

10. **Runtime requirements**: new binaries or services go into the docs
    proposal (README, `.claude/rules/oddjob.md` "Runtime needs").

Tests: `tests/test_<backend module>.py` for the backend (options model,
adapter against a fake executable or `FakeHTTPServer`, `__oddjob_plugin__`
triples) plus an `*IntegrationTest` class reading `ODDJOB_TEST_*`; CLI tests
for `-n` with no backend configured.
