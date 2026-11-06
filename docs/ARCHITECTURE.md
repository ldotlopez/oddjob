# Architecture

glados is a set of file-in/file-out tasks. Each task is a click command that builds a
`Job` from pipeline steps, gets a backend for its task Protocol, and runs the job with
progress reporting.

```
glados/
  cli.py              entry point: `glados` group, one subcommand per task
  tasks/              one module per task: steps + click command; protocols.py
  core/               task-agnostic machinery
    cli_common.py     GladosContext, shared click options (file, backend, model, logging)
    config.py         Config model, config file loading and validation
    backends.py       backend discovery (entry-point metadata), selection, loading
    pipeline.py       Job, ProgressStep Protocol, destination policies
    progress.py       ProgressEvent/ProgressStream, rich and plain reporters
    runners.py        FFMpegRunner (ffmpeg/ffprobe subprocess with progress)
  plugins/            backend modules, each providing one or more backends (only backends live here)
    whisper.py        whisper (OpenAI CLI) and whisper_cpp (whisper-cli), implement transcribe
```

## Layers

- **Entry points**: `glados/cli.py` and each task's `cli` command, both installed
  through `[project.scripts]`, so a task is the same `click.Command` whether it runs as
  `glados <task>` or standalone. Commands only parse options, ask `GladosContext` for
  the backend and hand a `Job` to `GladosContext.run_job`.
- **Core** (`core/`): orchestration with no task knowledge. `Job` chains
  `ProgressStep[Path]` steps, each consuming the previous step's output path, and moves
  the last result to the destination; intermediates are deleted.
- **Contracts** (`tasks/protocols.py`): one `Protocol` per task (`Transcriber`,
  `Rewriter`, `Summarizer`, `Expander`) plus `TranscriptSegment`. Backends satisfy them
  structurally.
- **Adapters**: `core/runners.py` (ffmpeg) and the backends in `plugins/` (`whisper`,
  `whisper-cli`).
  They do the subprocess I/O and report progress as a `ProgressStream`.

## Data flow (transcribe)

```
transcribe FILE
  -> GladosContext.backend("transcribe", Transcriber, -b, {"model": -m})
       config (lazy) -> backends.select -> backends.load -> e.g. WhisperCppBackend
  -> Job([AudioExtractor, TranscribeStep], dest = FILE.<format> or -o)
       AudioExtractor: ffmpeg -> temp mono 16 kHz WAV
       TranscribeStep: Transcriber.transcribe -> segments -> FORMATTERS[format] -> temp file
  -> move temp file to destination
```

Steps and backends yield `ProgressEvent`s; the final event has `done=True` and carries
the result. `Job` feeds the events to a reporter from `progress.create_reporter()`.

## Backends

Which backend implements which task is declared in `pyproject.toml`, one entry-point
group per task, so it is known without importing any backend
([decision 0002](decisions/0002-one-module-many-backends.md), superseding
[0001](decisions/0001-backend-capabilities-in-entry-point-metadata.md)). The entry
point's name is the backend; its value names the module, and one module may provide
several backends:

```toml
[project.entry-points."glados.backends.transcribe"]
whisper = "glados.plugins.whisper:__glados_plugin__"
whisper_cpp = "glados.plugins.whisper:__glados_plugin__"
```

Only the selected backend's module is imported, through `foundation.plugin.Register`.
Its `__glados_plugin__(backend, options)` builds only the named backend, validates the
merged options with that backend's own pydantic model (`extra="forbid"`) and returns
`(task, Protocol, object)` triples.

To add a backend: in a new or existing `glados/plugins/<module>.py`, add its options
model, have `__glados_plugin__` build it under its name, add one entry-point line per
task it implements, then `uv sync`.

## Configuration

`GladosContext.config()` loads the config on first use (never at import): `.env`, then
`$XDG_CONFIG_HOME/glados/config.toml` with `${VAR}` expansion, validated into the frozen
`Config` model and checked against the installed backends. A missing file is an empty
config.

## Console and logging

Both come from `foundation`:

- `progress.py` draws through `foundation.clilib.get_stderr_console()` and picks the
  rich or plain reporter from `RICH_STDERR_ENABLED`.
- `cli_common.logging_options` adds `--log-level`/`-v`/`-q` to every task command and
  calls `foundation.loglib.setup_logger_from_click("glados", ...)`. Without flags the
  level comes from `GLADOS_LOG_LEVEL`, else `warning`. Modules log via
  `logging.getLogger(__name__)`; log records and progress bars share the stderr console.
