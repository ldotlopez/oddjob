# oddjob

- Implemented tasks: `transcribe` (backends `whisper`, `whisper_cpp`), `speak`
  (backend `piper`; text files, `--text` or stdin to WAV; text and stdin need `-o`)
  and the text
  tasks `rewrite`, `summarize`, `expand`, `translate`, `describe` (backends
  `openai`, `ollama`, `llm`; `describe` takes images and needs a vision model, and
  replies in `-l` or else the system locale's language: `Prompts.render_describe`
  appends "Reply in <language>.", not a template placeholder), and
  `audio-grep` (system grep over cached transcripts, through the `transcribe`
  backends; decision 0006).
- File commands (no backends or config): `sidecars`, `motionphotos`, `jpgize`, `mp4ize`, `img-hash`,
  `img-duplicates`, `img-check`, `img-trim`, `img-reduce`, `img-embed-description`,
  `photo-lint` (`check`, `set-zone`), `rename-by-hash`, `fix-extensions`, `date-copy`, `cleanup`.
- One tool (`docs/decisions/0003`): run every command as `uv run oddjob <command>
  PATH...`; `oddjob` is the only installed script. A command may resolve a backend
  and do file work in one run.
- Layout (`docs/decisions/0003`): `oddjob/cli.py` is the click group (help
  panels by subject), `oddjob/commands/<command>.py` one click command or family
  each (wiring only, objects named `<name>_cmd`), and `oddjob/lib/` holds the
  domain modules, flat, with no config, backends or CLI (only where a command has
  logic beyond wiring). click may be imported only in `cli.py`,
  `commands/`, `filejobs/cli_*.py` and `oddjob/core/cli_*.py`;
  `tests/test_boundaries.py` fails otherwise.
- Every command that writes a file runs a `Job` through `run_jobs`; reports,
  renames and checks are plain functions under `run_batch` (`docs/decisions/0004`).
- The backend-free core is `filejobs/` (`pipeline`, `progress`, `runners`, `inputs`,
  `batch`, `cli_options`; `docs/decisions/0003`); `oddjob/core/` holds the backend
  part. Boundaries: filejobs imports nothing from oddjob; `oddjob.lib` imports none
  of `oddjob.core`, `oddjob.plugins`, `oddjob.commands`; `oddjob.plugins` imports
  only `oddjob.lib`. `tests/test_boundaries.py` checks them. Only commands taking
  `pass_session` reach config or backends; file commands never do.
- File commands' runtime binaries: ImageMagick (`magick`/`convert`), `exiftool`,
  `ffmpeg`/`ffprobe`. The Pillow code (`imghash`, `imgedit`: `img-hash`,
  `img-duplicates`, `img-check`, `img-trim`, `img-reduce`) and its tests need the extra:
  `uv sync --extra images`; commands load it through `load_extra_module`.
- Runtime needs `ffmpeg` and `ffprobe` on PATH, plus the selected transcribe
  backend's CLI: `whisper-cli` (`whisper_cpp`) or `whisper` from `openai-whisper`
  (`whisper`). Default models: `platformdirs.user_data_dir("whisper")/default-model.bin`
  for `whisper_cpp`, `turbo` for `whisper`; override with `-m`. Text backends need
  their service (OpenAI-compatible API, Ollama) or the `llm` CLI.
- Text backends are only `lib.text_backend.ChatTransport`s (`complete(system, user,
  images=())`); `TextBackend` adapts a transport to every text task Protocol
  (`Rewriter`, `Summarizer`, `Expander`, `Translator`, `Describer`) and
  `text_plugin_triples()` is the
  plugin's return value. Prompts live in `Config.prompts` (`[prompts]`), owned by the
  tasks, never in a backend.
- Backends live in `oddjob/plugins/<module>.py`; one module may provide several
  backends (e.g. `whisper.py`: `whisper` and `whisper_cpp`). Never put non-plugin
  modules there.
- Which backend implements which task is declared in `pyproject.toml`, one
  entry-point group per task (`oddjob.backends.<task>`). The set of these groups is
  the task list (`core.backends.tasks()`): a new task needs its group, nothing
  else lists tasks. The name is the backend,
  and the value must be `oddjob.plugins.<module>:__oddjob_plugin__`; a backend must
  name the same module in every group. Run `uv sync` after editing it. See
  `docs/decisions/0001`.
- `__oddjob_plugin__(backend, options)` builds only the named backend, validating
  its global options with that backend's own pydantic model (`extra="forbid"`,
  defaults for everything), and returns `(task name, task Protocol, object)`
  triples, one per task. It is loaded through `foundation.plugin.Register`
  (`core/backends.py`, keyed by module), and only for the selected backend.
- Backend selection per task: `-b`, then `ODDJOB_<TASK>_BACKEND`, then `[tasks]` in
  the config, then the only installed implementor. Options: model defaults, then
  `[backends.<name>]`, then `[backends.<name>.tasks.<task>]` (decision 0002; `tasks`
  is a reserved key), then CLI overrides (`-m` → `model`). Per-run values are
  method arguments, not options.
- Config is optional: `$XDG_CONFIG_HOME/oddjob/config.toml`, `${VAR}` expanded,
  `.env` loaded. It is read on first use in `Session` (`core/session.py`),
  injected by `pass_session`, never at import.
- One user cache for every command (`docs/decisions/0007`): open it with
  `oddjob.core.cache.open_user_cache()` (180-day expiry, 1 GiB, least recently used
  dropped first) and key entries with `oddjob.lib.cache.cache_key("<tool>", version,
  ...)`, i.e. `<tool>/<digest>`, with no paths in the key; lib code receives the store
  as a `ByteStore`. Include everything that changes the cached value (content, prompt,
  backend, effective options via `Session.backend_options`) and bump the layout version
  when the value's format changes.
- The backend registry is a deliberate exception to `architecture.md`'s "no plugin
  registries" rule: backends are the replaceable part here. Keep it.
- Nothing is imported until a backend is selected. A broken backend fails only
  when selected, with a clear error. Options of unused backends are not
  validated.
- Tasks whose output has the same extension as the input must use
  `infix_destination`; `suffix_destination` would overwrite the input.
- Console and logging come from `foundation`: progress reporters use
  `foundation.clilib.get_stderr_console()`/`RICH_STDERR_ENABLED`; every command
  takes `--log-level`/`-v`/`-q` after its name via `cli_common.logging_options`
  (`audio-grep`: `--log-level` only; the group takes none), which sets up the
  `oddjob` logger with `foundation.loglib` (`ODDJOB_LOG_LEVEL` when no flag is given)
  and gives the `filejobs` logger the same level. Silent on success (decision 0004):
  `wrote <dest>` and plain progress are INFO, shown with `-v`.
  Modules log through `logging.getLogger(__name__)`.
- Tests: `uv run python -m unittest discover -s tests` (stdlib unittest; see
  `docs/ARCHITECTURE.md`, "Tests"). Unit tests use fake executables and
  `support.FakeHTTPServer`, never real services. Integration tests read
  `tests/integration.env` (git-ignored, holds secrets: never commit or print it) and
  skip when unconfigured.
  The file commands' integration tests (`test_file_integration.py`) run the real
  ImageMagick, exiftool and ffmpeg and skip when one is missing from PATH.
- `speak` needs `piper` (piper-tts) on PATH and a voice `.onnx` (default
  `platformdirs.user_data_dir("piper")/default-voice.onnx`; override with `-m`).
- Call `whisper-cli` with long options only: it exits 0 on an unknown argument, so a
  wrong short flag fails silently. Its default language is `en`; pass `auto`.
