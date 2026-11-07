# Plan: a click-free `Glados` facade for config and backends

Status: draft (2026-11-07).

## Context

Every glados command gets its config and backend through
`GladosContext` (`glados/core/cli_common.py`), a click context object that
loads the config on first use and turns `ConfigError`/`BackendError` into
`click.ClickException`. The pieces it wraps (`load_dotenv`, `config_path`,
`load_config`, `check_config`, `core.backends.resolve`) are already
click-free, but the only way to get them together, lazily and cached, is
through click.

So Python code that wants a backend (a composed tool, a script, a test)
must either rebuild that sequence by hand or invoke a click command. The
second option parses argv, raises `SystemExit`/`ClickException`, re-runs
logging setup and returns files instead of values.

This plan adds the missing piece: a plain object, `Glados`, that owns the
lazy config and hands out typed backends, with `GladosContext` reduced to
an adapter over it. It changes no behavior and adds no composed command;
it only makes the domain layer (`glados.tasks.*`, task Protocols) reachable
from Python with a backend in hand.

## Goals

- Get a typed backend from Python without click:
  `Glados().backend("describe", Describer, choice, overrides) -> Describer`.
- Config read on first use and cached per `Glados` instance, never at
  import; same sources and order as today (`.env`, then
  `$XDG_CONFIG_HOME/glados/config.toml`, `${VAR}` expansion, validation,
  `check_config`).
- Errors as the existing specific exceptions (`ConfigError`,
  `BackendError`); only the click adapter turns them into exit codes.
- Testable without patching: the config source is injected.
- CLI behavior, messages and exit codes unchanged.

## Non-goals

These came up in the same review. Each is its own follow-up, not part of
this plan:

- Composed commands (e.g. describe + caption in one run).
- Per-task backend options (two tasks on the same backend with different
  models).
- One source for the task list (`core.backends.TASKS` vs entry-point
  groups).
- `Job.run` unlinking a step's output that is the job's input
  (pass-through steps).
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
  second call retries. Today's CLI calls `config()` once per run, so this
  only matters for Python callers.
- **`load_dotenv` stays in the default loader.** It mutates `os.environ`,
  so it is a side effect of the first `config()` call, as today. Injected
  loaders don't run it.
- **Module name `session`**, not `glados.core.glados`, so the import line
  doesn't stutter: `from glados.core.session import Glados`.

### `glados/core/cli_common.py`: `GladosContext` becomes an adapter

```python
@dataclass(slots=True)
class GladosContext:
    """Click adapter over Glados: the same calls, with config and backend
    errors turned into a clean message and exit code."""

    glados: Glados = field(default_factory=Glados)

    def config(self) -> Config:
        try:
            return self.glados.config()
        except (ConfigError, BackendError) as exc:
            raise click.ClickException(str(exc)) from exc

    def backend[T](self, task, protocol, choice, overrides) -> T:
        try:
            return self.glados.backend(task, protocol, choice, overrides)
        except (ConfigError, BackendError) as exc:
            raise click.ClickException(str(exc)) from exc
```

- `pass_glados_context` (`make_pass_decorator(..., ensure=True)`) still
  builds a default instance, so standalone scripts (`uv run transcribe`)
  keep working with no group.
- `backend()` now also catches `ConfigError`. Today a config error is
  raised from `config()` inside `backend()` and already becomes a
  `ClickException`, so the result is the same; the catch only makes it
  explicit.
- The `load_dotenv`/`config_path`/`load_config`/`check_config` imports
  leave `cli_common.py`.
- No command module changes.

## Steps

1. **Add `glados/core/session.py`** with `load_default_config` and
   `Glados` as above. It imports no click, so `tests/test_boundaries.py`
   covers it with no change (it is not a `cli_*.py` module).
2. **Make `GladosContext` delegate to `Glados`** (as above) and drop the
   loading code from `cli_common.py`.
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
   - `GladosContext` turns a loader's `ConfigError` into
     `click.ClickException` with the same message (a `GladosContext` built
     with an injected `Glados`).
4. **Check.** `uv run ruff check --fix .`, `uv run ruff format .`,
   `uv run python -m unittest discover -s tests`, and a manual run
   showing that a broken config gives the same message and exit code as
   before: `XDG_CONFIG_HOME=<dir with bad config.toml> uv run glados
   summarize x.txt`, and the same through `uv run summarize`.
5. **Docs (ask first, per CLAUDE.md).** Proposed edits, applied only after
   a yes:
   - `docs/ARCHITECTURE.md`: add `session.py` to the `core/` tree
     ("`Glados`: config and backends without click"); in "Configuration",
     the config is loaded on first use by `Glados.config()`, which
     `GladosContext` wraps.
   - `.claude/rules/glados.md`: "read on first use in `GladosContext`"
     becomes "in `Glados` (`core/session.py`), wrapped by `GladosContext`".
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
  (`load_dotenv` before `config_path`) must move verbatim; step 4's manual
  run checks the error path.
- **Mutable default in dataclass.** `GladosContext.glados` uses
  `field(default_factory=Glados)`, not `= Glados()`. A shared default
  instance would cache one config across contexts, which tests building
  several contexts would notice.
- **Callers outside click get raw exceptions.** That's the intent. Python
  callers handle `ConfigError`/`BackendError` themselves.
