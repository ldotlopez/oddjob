# glados

- Implemented tasks: `transcribe` (backends `whisper`, `whisper_cpp`) and the text
  tasks `rewrite`, `summarize`, `expand` (backends `openai`, `ollama`, `llm`).
  `describe`/`tts` in the pyproject description don't exist.
- Run tasks via `uv run glados <task> FILE ...`; each task is also a standalone
  script (`uv run transcribe FILE`) using the same click.Command.
- Runtime needs `ffmpeg` and `ffprobe` on PATH, plus the selected transcribe
  backend's CLI: `whisper-cli` (`whisper_cpp`) or `whisper` from `openai-whisper`
  (`whisper`). Default models: `platformdirs.user_data_dir("whisper")/default-model.bin`
  for `whisper_cpp`, `turbo` for `whisper`; override with `-m`. Text backends need
  their service (OpenAI-compatible API, Ollama) or the `llm` CLI.
- Text backends are only `core.text_backend.ChatTransport`s; `TextBackend` adapts a
  transport to `Rewriter`/`Summarizer`/`Expander` and `text_plugin_triples()` is the
  plugin's return value. Prompts live in `Config.prompts` (`[prompts]`), owned by the
  tasks, never in a backend.
- Backends live in `glados/plugins/<module>.py`; one module may provide several
  backends (e.g. `whisper.py`: `whisper` and `whisper_cpp`). Never put non-plugin
  modules there.
- Which backend implements which task is declared in `pyproject.toml`, one
  entry-point group per task (`glados.backends.<task>`). The name is the backend,
  and the value must be `glados.plugins.<module>:__glados_plugin__`; a backend must
  name the same module in every group. Run `uv sync` after editing it. See
  `docs/decisions/0002`.
- `__glados_plugin__(backend, options)` builds only the named backend, validating
  its global options with that backend's own pydantic model (`extra="forbid"`,
  defaults for everything), and returns `(task name, task Protocol, object)`
  triples, one per task. It is loaded through `foundation.plugin.Register`
  (`core/backends.py`, keyed by module), and only for the selected backend.
- Backend selection per task: `-b`, then `GLADOS_<TASK>_BACKEND`, then `[tasks]` in
  the config, then the only installed implementor. Options: model defaults, then
  `[backends.<name>]`, then CLI overrides (`-m` → `model`). Per-run values are
  method arguments, not options.
- Config is optional: `$XDG_CONFIG_HOME/glados/config.toml`, `${VAR}` expanded,
  `.env` loaded. It is read on first use in `GladosContext`, never at import.
- The backend registry is a deliberate exception to `architecture.md`'s "no plugin
  registries" rule: backends are the replaceable part here. Keep it.
- Nothing is imported until a backend is selected. A broken backend fails only
  when selected, with a clear error. Options of unused backends are not
  validated.
- Tasks whose output has the same extension as the input must use
  `infix_destination`; `suffix_destination` would overwrite the input.
- Console and logging come from `foundation`: progress reporters use
  `foundation.clilib.get_stderr_console()`/`RICH_STDERR_ENABLED`; every task command
  takes `--log-level`/`-v`/`-q` via `cli_common.logging_options`, which sets up the
  `glados` logger with `foundation.loglib` (`GLADOS_LOG_LEVEL` when no flag is given).
  Modules log through `logging.getLogger(__name__)`.
- Tests: `uv run python -m unittest discover -s tests` (stdlib unittest; see
  `docs/ARCHITECTURE.md`, "Tests"). Unit tests use fake executables and
  `support.FakeHTTPServer`, never real services. Integration tests read
  `tests/integration.env` (git-ignored, holds secrets: never commit or print it) and
  skip when unconfigured. The `whisper` (OpenAI CLI) backend has no tests yet.
- Call `whisper-cli` with long options only: it exits 0 on an unknown argument, so a
  wrong short flag fails silently. Its default language is `en`; pass `auto`.
