# Plan: a click-free `Glados` facade for config and backends

Status: draft (2026-11-07).

## Context

Every glados command gets its config and backend through
`GladosContext` (`glados/core/cli_common.py`), click's per-run context
object (`ctx.obj`, injected by `pass_glados_context`). It loads the config
on first use and turns `ConfigError`/`BackendError` into
`click.ClickException`. The pieces it wraps (`load_dotenv`, `config_path`,
`load_config`, `check_config`, `core.backends.resolve`) are already
click-free, but the only way to get them together, lazily and cached, is
through click.

So Python code that wants a backend (a composed tool, a script, a test)
must either rebuild that sequence by hand or invoke a click command. The
second option parses argv, raises `SystemExit`/`ClickException`, re-runs
logging setup and returns files instead of values.

This plan adds the missing piece: a plain object, `Glados`, that owns the
lazy config and hands out typed backends. `GladosContext` goes away: once
`Glados` holds the state, all that is left for click is converting errors,
and that belongs in the decorator that injects the object, not in a second
class with a misleading name. The plan changes no CLI behavior and adds no
composed command.

The plan also fixes a `Job.run` bug found in the same review (step 4): a
step whose output is its own input gets that file deleted or moved away.

## Goals

- Get a typed backend from Python without click:
  `Glados().backend("describe", Describer, choice, overrides) -> Describer`.
- Config read on first use and cached per `Glados` instance, never at
  import; same sources and order as today (`.env`, then
  `$XDG_CONFIG_HOME/glados/config.toml`, `${VAR}` expansion, validation,
  `check_config`).
- Errors as the existing specific exceptions (`ConfigError`,
  `BackendError`); only the click decorator turns them into exit codes.
- Testable without patching: the config source is injected.
- One name per concept: `Glados` is the state, `pass_glados` is the click
  glue.
- CLI behavior, messages and exit codes unchanged.
- `Job.run` never deletes or moves a file it did not create.

## Non-goals

These came up in the same review. Each is its own follow-up, not part of
this plan:

- Composed commands (e.g. describe + caption in one run).
- Per-task backend options (two tasks on the same backend with different
  models).
- One source for the task list (`core.backends.TASKS` vs entry-point
  groups).
- A `prompts` helper on the facade: callers keep using
  `glados.config().prompts.render_*`.
- Caching backend objects: `backend()` resolves on every call, as
  `GladosContext.backend` does today. A caller reuses the object it got.

## Design

### `glados/core/session.py` (new, no click)

```python
type ConfigLoader = Callable[[], Config]


def load_default_config() -> Config:
    """`.env`, then config_path(), loaded and checked against the installed
    backends. Raises ConfigError or BackendError."""
    load_dotenv()
    path = config_path()
    LOGGER.debug("config: %s (%s)", path, "found" if path.is_file() else "not found")
    cfg = load_config(path)
    check_config(cfg)
    return cfg


class Glados:
    """glados' config and backends for one run, without click. The config
    is loaded on first use and cached; nothing happens at construction."""

    def __init__(self, load: ConfigLoader = load_default_config) -> None:
        self._load = load
        self._config: Config | None = None

    def config(self) -> Config:
        if self._config is None:
            self._config = self._load()
        return self._config

    def backend[T](
        self,
        task: str,
        protocol: type[T],
        choice: str | None = None,
        overrides: Mapping[str, object] | None = None,
    ) -> T:
        """The backend object for `task`, checked against `protocol`: see
        core.backends.resolve. Raises BackendError (or ConfigError on the
        first call, from loading the config)."""
        return resolve(task, protocol, choice, self.config(), overrides or {})
```

Decisions inside the design:

- **The Protocol stays in the call.** `resolve` checks the loaded object
  against it, so a backend missing a method fails at load with a clear
  error, and the return type is `T`, not `object`.
- **The loader is a callable, not a path.** Tests pass
  `lambda: Config(...)`. That skips `.env` and the filesystem and needs no
  patching. `load_default_config` keeps today's sequence verbatim, moved
  out of `GladosContext.config`.
- **A failed load is not cached.** `_config` is set only on success, so a
  second call retries. A CLI run exits on the first error, so this only
  matters for Python callers.
- **`load_dotenv` stays in the default loader.** It mutates `os.environ`,
  so it is a side effect of the first `config()` call, as today. Injected
  loaders don't run it.
- **Module name `session`**, not `glados.core.glados`, so the import line
  doesn't stutter: `from glados.core.session import Glados`.

### `glados/core/cli_common.py`: `pass_glados` replaces `GladosContext`

`GladosContext` and `pass_glados_context` are removed. `Glados` itself is
click's `ctx.obj`:

```python
def pass_glados[**P, R](func: Callable[Concatenate[Glados, P], R]) -> Callable[P, R]:
    """Passes the run's Glados as the first argument (the one the `glados`
    group's context already holds, or a new one when the command runs
    standalone) and turns ConfigError/BackendError into ClickException."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        glados = click.get_current_context().ensure_object(Glados)
        try:
            return func(glados, *args, **kwargs)
        except (ConfigError, BackendError) as exc:
            raise click.ClickException(str(exc)) from exc

    return wrapper
```

- **Placement:** `@pass_glados` goes where `@pass_glados_context` is today,
  as the decorator nearest the function. `functools.wraps` copies the
  function's `__dict__`, so options collected so far
  (`__click_params__`) carry over, as with click's own
  `make_pass_decorator`.
- **Standalone scripts** (`uv run transcribe`) keep working:
  `ensure_object` creates the `Glados` when no group did.
- **Same errors converted as today.** In all six commands the backend is
  resolved in the command body before `run_jobs`, and per-input failures
  are `JOB_ERRORS`, handled inside `run_jobs`. Catching around the whole
  body converts exactly the `ConfigError`/`BackendError` that
  `GladosContext` converted, with the same message.
- The `load_dotenv`/`config_path`/`load_config`/`check_config` imports
  leave `cli_common.py`. `backend_option`, `model_option` and
  `logging_options` stay.

### Commands (`glados/commands/*.py`, six modules)

A mechanical change in each: `@pass_glados_context` becomes
`@pass_glados`; `ctx: GladosContext` becomes `glados: Glados`;
`ctx.config()`/`ctx.backend(...)` become
`glados.config()`/`glados.backend(...)`. No other edits.

### `Job.run` (`filejobs/pipeline.py`): only touch files the job created

Today every step output goes into `intermediates`. After the run, all of
them are unlinked except the one moved to `dest`, and the last one is
moved with `move_to_destination`. A step that returns its own input
unchanged (a pass-through, e.g. a "skip if already done" step) breaks
both:

- a pass-through **before** a producing step puts `input_path` (or an
  earlier temp file) in `intermediates`, so the user's input is
  **deleted** on cleanup, on success and on failure alike;
- a pass-through as the **last** step makes `current == input_path`, so
  the input is **moved** (renamed) to `dest`, leaving nothing where it
  was.

Fix:

- Record a step's output as an intermediate only if it differs from that
  step's input and from `input_path`. Then `intermediates` holds only
  temp files the steps created, each once.
- At the end, if `current == input_path` (no step produced anything):
  when `dest == input_path` there is nothing to move; otherwise
  `copy_into_place(input_path, dest)`, after the same `check_destination`
  re-check that `move_to_destination` does. Otherwise move `current` as
  today.
- Cleanup unlinks every intermediate except the one moved to `dest`.

Steps that produce a new temp file, which is all of them today, behave
exactly as before.

## Steps

1. **Add `glados/core/session.py`** with `load_default_config` and
   `Glados` as above. It imports no click, so `tests/test_boundaries.py`
   covers it with no change (it is not a `cli_*.py` module).
2. **Replace `GladosContext` with `pass_glados`** in `cli_common.py`, and
   update the six command modules as above.
3. **Add `tests/test_session.py`** (stdlib unittest, no real services):
   - `Glados(load)` does not call `load` at construction; `config()` calls
     it once and returns the same object on later calls.
   - A loader that raises `ConfigError` propagates it unchanged, and the
     next `config()` call retries.
   - `backend()` with an unknown backend name (`choice="nope"`) raises
     `BackendError` naming the available ones.
   - `backend()` for `summarize` with `Config(tasks={"summarize":
     "openai"}, backends={"openai": {...}})` returns an object that
     satisfies `Summarizer`. This uses the real entry points of the dev
     install. Building the openai backend only validates `OpenAIOptions`;
     the API key is checked on the first `complete()` call
     (`glados/plugins/openai.py`), so the test needs no network or key.
   - `pass_glados`: a throwaway click command decorated with it, run with
     a context whose `obj` is a `Glados` with a raising loader, exits 1
     with the loader's message. Run without an `obj`, it receives a new
     `Glados`.
4. **Fix `Job.run`** as above, with regression tests in
   `tests/test_filejobs.py`:
   - a pass-through step followed by a producing step: the input still
     exists after success, and after the producing step fails;
   - a pass-through as the only step, `dest != input_path`: `dest` is a
     copy, and the input is still in place;
   - the same, `dest == input_path`: nothing is moved and the input is
     unchanged;
   - existing tests: intermediate temp files are still removed.
5. **Check.** `uv run ruff check --fix .`, `uv run ruff format .`,
   `uv run python -m unittest discover -s tests`, and a manual run
   showing that a broken config gives the same message and exit code as
   before: `XDG_CONFIG_HOME=<dir with bad config.toml> uv run glados
   summarize x.txt`, and the same through `uv run summarize`.
6. **Docs (ask first, per CLAUDE.md).** Proposed edits, applied only after
   a yes:
   - `docs/ARCHITECTURE.md`: add `session.py` to the `core/` tree
     ("`Glados`: config and backends without click"); `cli_common.py`'s
     entry says `pass_glados` instead of `GladosContext`; the data-flow
     lines `GladosContext.backend(...)` become `Glados.backend(...)`; in
     "Configuration", the config is loaded on first use by
     `Glados.config()`.
   - `.claude/rules/glados.md`: "read on first use in `GladosContext`"
     becomes "in `Glados` (`core/session.py`), injected by `pass_glados`".
   - No decision record: this adds a module inside an existing boundary
     and reverses nothing.

## Usage once done

```python
from glados.core.session import Glados
from glados.tasks.describe import describe_image
from glados.tasks.protocols import Describer

glados = Glados()
describer = glados.backend("describe", Describer, overrides={"model": "llava"})
prompt = glados.config().prompts.render_describe(None)
text = describe_image(describer, prompt, image, reporter)
```

## Risks

- **Hidden behavior in the move.** The debug log line and the order
  (`load_dotenv` before `config_path`) must move verbatim; step 5's manual
  run checks the error path.
- **Decorator order.** `@pass_glados` must stay the decorator nearest the
  function, as `@pass_glados_context` is now; above a click option it
  would shift arguments. Every command is covered by step 5's suite and
  manual run.
- **Callers outside click get raw exceptions.** That's the intent. Python
  callers handle `ConfigError`/`BackendError` themselves.
- **`Job.run` behavior change for pass-through steps.** Intended: no step
  does this today, so no current command changes behavior; the new tests
  pin the new behavior.
