# Architecture

The repository holds two command-line tools in one distribution
([decision 0003](decisions/0003-multitool-in-the-same-distribution.md)):

- **glados**: file-based tasks backed by models. Each task is a click command that
  builds a `Job` from pipeline steps, gets a backend for its task Protocol, and runs the
  job over every input with progress reporting.
- **multitool**: file utilities (sidecars, motion photos, conversions, image hashes,
  renames) with no backends (see [multitool](#multitool)).

Both build on **filejobs**, the backend-free core they share
([decision 0006](decisions/0006-filejobs-package.md)).

Every command takes several files and directories (see [Inputs](#inputs)).

```
filejobs/             backend-free core shared by both tools
  cli_options.py      backend-free click options, run_jobs/job_action, print_plan (-n), finish_batch
  inputs.py           PATH... expansion into input files, per-command file filters
  batch.py            run_batch: one action per input, failures logged and collected
  pipeline.py         Job, ProgressStep Protocol, TextStep, land_text_stream, BytesStep, destination policies, JOB_ERRORS
  progress.py         ProgressEvent/ProgressStream, rich and plain reporters
  runners.py          FFMpegRunner (ffmpeg/ffprobe subprocess with progress)
glados/
  cli.py              entry point: `glados` group, one subcommand per task
  commands/           one click command per task (transcribe, rewrite, summarize, expand, translate, describe)
  tasks/              task domain code: protocols.py (task Protocols), transcribe.py (steps, formatters),
                      translate.py (language -> file name infix), describe.py (DescribeStep),
                      text_backend.py (ChatTransport Protocol; TextBackend: every text task over it)
  core/               glados' backend machinery
    cli_common.py     GladosContext, backend/model options, glados' logging options
    config.py         Config model, config file loading and validation
    backends.py       backend discovery (entry-point metadata), selection, loading
  plugins/            backend modules, each providing one or more backends (only backends live here)
    whisper.py        whisper (OpenAI CLI) and whisper_cpp (whisper-cli): transcribe
    openai.py         openai (Chat Completions, any compatible server): text tasks
    ollama.py         ollama (native /api/chat): text tasks
    llm.py            llm (the llm CLI): text tasks
multitool/
  cli.py              entry point: `multitool` group
  commands/           one module per tool: sidecars, motionphotos, conversions (jpgize, mp4ize),
                      imghash (img-hash, img-duplicates, img-check), imgedit (autocrop),
                      captions (img-caption), renames (hash-rename, fix-extensions),
                      subtitles (srt-grep)
  sidecars.py, motionphotos.py, conversions.py, imghash.py, imgedit.py, captions.py,
  renamers.py, subtitles.py
                      domain code: grouping, motion-photo parsing, conversion steps, average hash
                      and decode checks, autocrop, caption planning and step, rename planning,
                      SRT parsing and search
  media.py            which files are images/videos and which ones each converter takes
  external.py         ImageMagick and exiftool adapters, user commands
tests/                unittest suite: one module per backend module or tool area; support.py: shared fakes
```

## Layers

- **Entry points**: `<tool>/cli.py` (the click group) and `<tool>/commands/` (one click
  command each), the same layout in both tools
  ([decision 0005](decisions/0005-one-command-layout.md)). glados' task commands are
  also installed on their own through `[project.scripts]`, so a task is the same
  `click.Command` whether it runs as `glados <task>` or standalone. Commands only parse
  options, expand inputs, wire adapters (glados: the backend, from `GladosContext`) and
  hand the work to `run_jobs` or `run_batch`. click is imported only in `cli.py`,
  `commands/`, `filejobs/cli_*.py` and `glados/core/cli_*.py`;
  `tests/test_boundaries.py` enforces it.
- **Domain** (`glados/tasks/`, multitool's top-level modules): steps, formatters,
  parsing and planning, with no CLI. A command that only wires shared core pieces (the
  text tasks: one `TextStep`) has no domain module.
- **Core**: orchestration with no task knowledge, in two packages. `filejobs/`
  (`pipeline`, `progress`, `runners`, `inputs`, `batch`, `cli_options`) is shared by
  both tools: `Job` chains `ProgressStep[Path]` steps, each consuming the previous
  step's output path, and moves the last result to the destination; intermediates are
  deleted. `glados/core/` (`backends`, `config`, `cli_common`) is glados' backend
  part, used only by glados.
- **Contracts** (`tasks/protocols.py`): one `Protocol` per task (`Transcriber`,
  `Rewriter`, `Summarizer`, `Expander`) plus `TranscriptSegment`. Backends satisfy them
  structurally.
- **Adapters**: `filejobs/runners.py` (ffmpeg) and the backends in `plugins/`: subprocesses
  (`whisper`, `whisper-cli`, `llm`) and HTTP (`openai`, `ollama`, via `requests`). They
  do the I/O and report progress as a `ProgressStream`.

## Inputs

Commands take `PATH...` (`cli_options.paths_argument`), mixing files and directories,
expanded by `filejobs/inputs.expand_inputs`:

- A file argument is used as is.
- A directory argument is walked recursively, and contributes the files the command
  accepts (`transcribe`: audio/video; the text tasks: text files except their own
  earlier outputs, `<name>.<infix>.<ext>`, so a second run on a directory does not
  process its results). Which files qualify is the command's decision, not core's.
- Inputs keep argument order, each directory's files sorted, without duplicates.
  Then each input runs as its own `Job`, with its destination derived from that file
  (next to it). `Job` stays the unit of one input file → one output file.
- `-o/--output` names one destination, so it only applies when the arguments
  expand to exactly one file (`check_single_output`, a usage error otherwise).

Failure policy (`filejobs/batch.run_batch`, [decision 0004](decisions/0004-jobs-and-batches.md)):
an input that fails with one of `pipeline.JOB_ERRORS` (`OSError`, `RuntimeError`,
`ValueError`, `SubprocessError`) is logged and recorded, and the remaining inputs still
run. Anything else is a bug and propagates. `finish_batch` prints `N done, M failed`
and exits 1 if any input failed. `run_jobs` wraps both for commands that write files
and logs `wrote <dest>` at INFO for each result; on success nothing is printed
([decision 0007](decisions/0007-silent-on-success.md)).

`-n/--dry-run` (every command that changes files) prints the plan and returns before
any tool or backend is resolved: `input -> destination` for glados' tasks
(`print_plan`), each planned operation for multitool's.

## Landing results

Steps write temp files under `$TMPDIR`; `Job` moves the last one to the destination
with `pipeline.move_to_destination`, re-checking the destination first (`-y` to
replace it). On the same filesystem that is a rename. Across filesystems
(`EXDEV`), the file is copied next to the destination and renamed over it, so an
interrupted copy never leaves a truncated destination, also when replacing a file in
place (`motionphotos merge`, `strip -y`).

## Data flow (transcribe)

```
transcribe PATH...
  -> inputs = expand_inputs(PATH..., audio/video)
  -> GladosContext.backend("transcribe", Transcriber, -b, {"model": -m})
       config (lazy) -> backends.select -> backends.load -> e.g. WhisperCppBackend
  -> Job([AudioExtractor, TranscribeStep], dest = INPUT.<format> or -o)
       AudioExtractor: ffmpeg -> temp mono 16 kHz WAV
       TranscribeStep: Transcriber.transcribe -> segments -> FORMATTERS[format] -> temp file
  -> run_jobs: per input, run the Job and move its temp file to the destination
```

## Data flow (rewrite, summarize, expand, translate, describe)

```
rewrite PATH... -i INSTRUCTIONS
  -> inputs = expand_inputs(PATH..., text files except *.rewrite.*)
  -> prompt = config.prompts.render_rewrite(INSTRUCTIONS)     ([prompts] or default)
  -> GladosContext.backend("rewrite", Rewriter, -b, {"model": -m}) -> TextBackend
  -> Job([TextStep(text -> Rewriter.rewrite(text, prompt=prompt))],
         dest = INPUT.rewrite.<ext> or -o)
       TextStep: read UTF-8 -> transport.complete(prompt, text) streams the reply -> temp file
  -> run_jobs: per input, run the Job and move its temp file to the destination
```

`summarize` and `expand` have the same shape (`--max-length` / `--target-length` fill
the prompt's `{length}`; outputs `FILE.summary.<ext>`, `FILE.expanded.<ext>`). The LLM
backends are only `ChatTransport`s (one system prompt, one user message with optional
images, streamed reply); `tasks/text_backend.py` wraps a transport into one
`TextBackend` that satisfies `Rewriter`, `Summarizer`, `Expander`, `Translator` and
`Describer`, and `text_plugin_triples()` returns it under
all of them. Prompts belong to the tasks, not to the backends.

`translate -l LANGUAGE` has the same shape too: the language fills `{language}` and,
through `tasks/translate.language_infix`, names the output (`FILE.es.<ext>`).
`describe` takes images instead of text:

```
describe PATH... -i INSTRUCTIONS
  -> inputs = expand_inputs(PATH..., images)
  -> prompt = config.prompts.render_describe(INSTRUCTIONS)
  -> GladosContext.backend("describe", Describer, -b, {"model": -m}) -> TextBackend
  -> Job([DescribeStep], dest = INPUT.description.txt or -o)
       DescribeStep: transport.complete(prompt, "", images=[INPUT]) -> land_text_stream -> temp .txt
  -> run_jobs
```

Each transport attaches the images its own way: openai as `image_url` data-URI
content parts, ollama as base64 `images`, llm as `-a PATH`.

Steps and backends yield `ProgressEvent`s; the final event has `done=True` and carries
the result. `Job` feeds the events to a reporter from `progress.create_reporter()`.
In a batch, `run_batch` shows one overall bar and hands each input a reporter that
`remove()`s every step's bar once it completes.

## multitool

multitool has no backends, entry-point groups or config. Its commands use
filejobs: `Job` and `run_jobs` for every command that writes a file, plain
functions under `run_batch` for reports, renames and checks, and `cli_options` for
`PATH...`, `-y`, `-n` and logging (`logging_options_for("multitool")`).

- Commands that change files (`jpgize`, `mp4ize`, `motionphotos`, `autocrop`,
  `img-caption`, `hash-rename`, `fix-extensions`) plan first (`plan_conversions`,
  `plan_merges`, `plan_captions`, `plan_rename`, `plan_extension_fix`, or a destination
  per input), then apply, so `-n` prints the plan without touching anything or requiring
  the external tools or the extra.
- In-memory transforms (motion-photo join/split/strip) are `BytesStep`s; `jpgize` is
  `JpegConversionStep` (ImageMagick, then exiftool copies the tags except Orientation)
  and `mp4ize` is `Mp4RemuxStep` (ffmpeg through `filejobs/runners.py`, copying the video
  stream; the audio is copied or, failing that, re-encoded to AAC).
- `autocrop` is a `BytesStep` (Pillow); `img-caption` is `CaptionStep` (exiftool
  writes XMP-dc:Description and EXIF:ImageDescription into a copy, landed in place).
- `img-hash`, `img-duplicates`, `img-check` and `autocrop` need the `multitool` extra
  (Pillow, pillow-heif); `multitool.imghash` and `multitool.imgedit` are imported
  through `load_extra_module` only when one of them runs.
- `img-check` and `srt-grep` are reports: the problems or matches on stdout, exit 1 if
  there were any problems or no matches.

Boundary ([decision 0006](decisions/0006-filejobs-package.md)): multitool imports
nothing from glados, glados never imports multitool, and filejobs imports neither.
`tests/test_boundaries.py` checks all three.

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

## Tests

`uv run python -m unittest discover -s tests` (stdlib `unittest`, no test dependency).
Tests exercise backends directly (options model, transport/backend object,
`__glados_plugin__`), not through the CLI:

- **Unit tests** replace the outside world, not the code: subprocess backends run a fake
  executable written by `support.write_executable` (a Python script that records its argv
  and mimics the real CLI's output and failure modes); HTTP backends talk to
  `support.FakeHTTPServer`, which answers with a canned response and records requests.
- **Integration tests** (`*IntegrationTest`) run against the real CLI or service. They
  read `GLADOS_TEST_*` settings from `tests/integration.env` (git-ignored; template in
  `integration.env.example`), overridden by the environment, and skip their class when
  the backend's enabling setting is empty.
- **multitool** is tested through its domain modules, its conversion steps against fake
  executables, and its commands through click's `CliRunner`. Its integration tests
  (`tests/test_multitool_integration.py`) run the real ImageMagick, exiftool and
  ffmpeg and skip when a tool is not on `PATH`; the image-hash tests skip without the
  `multitool` extra.
- **Boundaries** (`tests/test_boundaries.py`) parse the sources with `ast`: the
  import boundaries between filejobs, glados and multitool, and where click may be
  imported.

The OpenAI `whisper` backend has no tests yet.

## Configuration

`GladosContext.config()` loads the config on first use (never at import): `.env`, then
`$XDG_CONFIG_HOME/glados/config.toml` with `${VAR}` expansion, validated into the frozen
`Config` model (`tasks`, `backends`, `prompts`) and checked against the installed
backends. A missing file is an empty config.

## Console and logging

Both come from `foundation`:

- `progress.py` draws through `foundation.clilib.get_stderr_console()` and picks the
  rich or plain reporter from `RICH_STDERR_ENABLED`. Rich bars are transient; the plain
  reporter logs its lines at INFO on `filejobs.progress`, so they show only with `-v`.
- `cli_common.logging_options` adds `--log-level`/`-v`/`-q` to every task command and
  calls `foundation.loglib.setup_logger_from_click("glados", ...)`. Without flags the
  level comes from `GLADOS_LOG_LEVEL`, else `warning`. It is
  `cli_options.logging_options_for("glados")`; multitool's group uses
  `logging_options_for("multitool")` (`MULTITOOL_LOG_LEVEL`). The shared `filejobs`
  logger gets the app logger's level, so `-v` and a bare `--log-level info` reach it
  (a bare level alone would only set the app logger); an explicit `filejobs:<level>`
  rule in `--log-level` wins. Modules log via
  `logging.getLogger(__name__)`; log records and progress bars share the stderr console.
