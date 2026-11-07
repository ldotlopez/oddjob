# glados

- Implemented tasks: `transcribe` (backends `whisper`, `whisper_cpp`) and the text
  tasks `rewrite`, `summarize`, `expand`, `translate`, `describe` (backends
  `openai`, `ollama`, `llm`; `describe` takes images and needs a vision model), and
  `audio-grep` (system grep over cached transcripts, through the `transcribe`
  backends; decision 0009).
- multitool commands: `sidecars`, `motionphotos`, `jpgize`, `mp4ize`, `img-hash`,
  `img-duplicates`, `img-check`, `autocrop`, `img-reduce`, `img-caption`,
  `hash-rename`, `fix-extensions`, `date-sync`, `fs-cleanup`.
- Run tasks via `uv run glados <task> PATH...`; each task is also a standalone
  script (`uv run transcribe PATH...`) using the same click.Command.
- Layout, shared by both tools (`docs/decisions/0005`): `<tool>/cli.py` is the
  click group, `<tool>/commands/<command>.py` one click command each (wiring only),
  domain modules hold the logic with no CLI (glados: `glados/tasks/`, only where a
  task has logic beyond wiring). click may be imported only in `cli.py`,
  `commands/`, `filejobs/cli_*.py` and `glados/core/cli_*.py`;
  `tests/test_boundaries.py` fails otherwise.
- Every command that writes a file runs a `Job` through `run_jobs`; reports,
  renames and checks are plain functions under `run_batch` (`docs/decisions/0004`).
- `multitool/` is a second tool in the same distribution (`docs/decisions/0003`),
  with no backends or config. The backend-free core both tools share is
  `filejobs/` (`pipeline`, `progress`, `runners`, `inputs`, `batch`,
  `cli_options`; `docs/decisions/0006`); `glados/core/` holds only glados' backend
  part. multitool never imports `glados`, glados never imports multitool, and
  filejobs imports neither. `tests/test_boundaries.py` checks all three.
- multitool's runtime binaries: ImageMagick (`magick`/`convert`), `exiftool`,
  `ffmpeg`/`ffprobe`. Its Pillow code (`imghash`, `imgedit`: `img-hash`,
  `img-duplicates`, `img-check`, `autocrop`, `img-reduce`) and their tests need the extra:
  `uv sync --extra multitool`; commands load it through `load_extra_module`.
- Runtime needs `ffmpeg` and `ffprobe` on PATH, plus the selected transcribe
  backend's CLI: `whisper-cli` (`whisper_cpp`) or `whisper` from `openai-whisper`
  (`whisper`). Default models: `platformdirs.user_data_dir("whisper")/default-model.bin`
  for `whisper_cpp`, `turbo` for `whisper`; override with `-m`. Text backends need
  their service (OpenAI-compatible API, Ollama) or the `llm` CLI.
- Text backends are only `tasks.text_backend.ChatTransport`s (`complete(system, user,
  images=())`); `TextBackend` adapts a transport to every text task Protocol
  (`Rewriter`, `Summarizer`, `Expander`, `Translator`, `Describer`) and
  `text_plugin_triples()` is the
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
  `[backends.<name>]`, then `[backends.<name>.tasks.<task>]` (decision 0010; `tasks`
  is a reserved key), then CLI overrides (`-m` → `model`). Per-run values are
  method arguments, not options.
- Config is optional: `$XDG_CONFIG_HOME/glados/config.toml`, `${VAR}` expanded,
  `.env` loaded. It is read on first use in `Glados` (`core/session.py`),
  injected by `pass_glados`, never at import.
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
  `glados` logger with `foundation.loglib` (`GLADOS_LOG_LEVEL` when no flag is given)
  and gives the `filejobs` logger the same level. Silent on success (decision 0007):
  `wrote <dest>` and plain progress are INFO, shown with `-v`.
  Modules log through `logging.getLogger(__name__)`.
- Tests: `uv run python -m unittest discover -s tests` (stdlib unittest; see
  `docs/ARCHITECTURE.md`, "Tests"). Unit tests use fake executables and
  `support.FakeHTTPServer`, never real services. Integration tests read
  `tests/integration.env` (git-ignored, holds secrets: never commit or print it) and
  skip when unconfigured. The `whisper` (OpenAI CLI) backend has no tests yet.
  multitool's integration tests (`test_multitool_integration.py`) run the real
  ImageMagick, exiftool and ffmpeg and skip when one is missing from PATH.
- Call `whisper-cli` with long options only: it exits 0 on an unknown argument, so a
  wrong short flag fails silently. Its default language is `en`; pass `auto`.
