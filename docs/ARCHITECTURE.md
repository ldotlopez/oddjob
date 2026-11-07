# Architecture

The repository holds one command-line tool, `glados`, whose commands are of two
kinds ([decision 0011](decisions/0011-one-tool.md)):

- **Tasks**: file-based work backed by models. Each task is a click command that
  builds a `Job` from pipeline steps, gets a backend for its task Protocol through
  `pass_glados`, and runs the job over every input with progress reporting.
- **File commands**: file utilities (sidecars, motion photos, conversions, image hashes
  and edits, renames, dates, cleanup) with no backends or config (see
  [File commands](#file-commands)).

A command may be both: resolve a backend and do file work. Every command builds on
**filejobs**, the backend-free core ([decision 0006](decisions/0006-filejobs-package.md)).

Every command takes several files and directories (see [Inputs](#inputs)).

```
filejobs/             backend-free core: no backends, config or glados imports
  cli_options.py      backend-free click options, run_jobs/job_action, print_plan (-n), finish_batch
  inputs.py           PATH... expansion into input files, per-command file filters
  batch.py            run_batch: one action per input, failures logged and collected
  pipeline.py         Job, consume_stream, ProgressStep Protocol, TextStep, land_text_stream, BytesStep, destination policies, JOB_ERRORS
  progress.py         ProgressEvent/ProgressStream, rich and plain reporters
  runners.py          FFMpegRunner (ffmpeg/ffprobe subprocess with progress)
glados/
  cli.py              entry point: the `glados` group, every command, help panels by subject
  commands/           one module per command or command family (wiring only):
                      tasks: transcribe, speak, rewrite, summarize, expand, translate, describe, audio_grep;
                      file commands: sidecars, motionphotos, conversions (jpgize, mp4ize),
                      imghash (img-hash, img-duplicates, img-check), imgedit (img-trim,
                      img-reduce), captions (img-embed-description), renames (rename-by-hash,
                      fix-extensions), dates (date-copy), cleanup (cleanup)
  lib/                domain code, no config, backends or CLI:
                      protocols.py (task Protocols), transcribe.py (steps, formatters),
                      speak.py (text source selection, SpeakStep),
                      translate.py (language -> file name infix), describe.py (describe_image, DescribeStep, CachedDescriber),
                      language.py (language code or locale -> language name, via langcodes),
                      cache.py (ByteStore Protocol; `<tool>/<digest>` cache keys, file digest),
                      text_backend.py (ChatTransport Protocol; TextBackend: every text task over it),
                      audio_grep.py (argument split, transcript cache, grep over transcripts),
                      grep.py (GrepRunner: the system grep);
                      sidecars.py, motionphotos.py, conversions.py, imghash.py, imgedit.py,
                      captions.py, renamers.py, dates.py, cleanup.py (grouping, motion-photo
                      parsing, conversion steps, average hash and decode checks, img-trim and
                      downscaling, caption planning and step, rename planning, date reading
                      and change planning, junk and permission planning);
                      media.py (which files are images/videos and which ones each converter
                      takes), external.py (ImageMagick and exiftool adapters, user commands),
                      shotwell.py (read-only adapter for a Shotwell library, for date-copy)
  core/               backend machinery
    session.py        Glados: config and backends without click
    describing.py     describe's language, prompt and cached backend, shared with img-embed-description
    cli_common.py     pass_glados (injects Glados), backend/model options, the logging options
    config.py         Config model, config file loading and validation
    backends.py       backend discovery (entry-point metadata), selection, loading
  plugins/            backend modules, each providing one or more backends (only backends live here)
    whisper.py        whisper (OpenAI CLI) and whisper_cpp (whisper-cli): transcribe
    piper.py          piper (piper-tts CLI): speak
    openai.py         openai (Chat Completions, any compatible server): text tasks
    ollama.py         ollama (native /api/chat): text tasks
    llm.py            llm (the llm CLI): text tasks
tests/                unittest suite: one module per backend module or command area; support.py: shared fakes
```

## Layers

- **Entry points**: `glados/cli.py` (the click group; the only installed script) and
  `glados/commands/` (one click command or command family each)
  ([decision 0005](decisions/0005-one-command-layout.md), 0011). Commands only parse
  options, expand inputs, wire adapters (tasks: the backend, from `Glados`) and
  hand the work to `run_jobs` or `run_batch`. click is imported only in `cli.py`,
  `commands/`, `filejobs/cli_*.py` and `glados/core/cli_*.py`;
  `tests/test_boundaries.py` enforces it.
- **Domain** (`glados/lib/`): steps, formatters, parsing and planning, with no config,
  backends or CLI. A command that only wires shared core pieces (the text tasks: one
  `TextStep`) has no domain module.
- **Core**: orchestration with no task knowledge, in two packages. `filejobs/`
  (`pipeline`, `progress`, `runners`, `inputs`, `batch`, `cli_options`) is the
  backend-free part: `Job` chains `ProgressStep[Path]` steps, each consuming the previous
  step's output path, and moves the last result to the destination; intermediates are
  deleted. `glados/core/` (`backends`, `config`, `session`, `cli_common`) is the backend
  part, reached only by commands that take `pass_glados`.
- **Contracts** (`lib/protocols.py`): one `Protocol` per task (`Transcriber`,
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
and logs `wrote <dest>` at INFO for each result; an action returning `None` wrote
nothing for that input (`img-reduce` skipping an image that already fits) and still
counts as done. On success nothing is printed
([decision 0007](decisions/0007-silent-on-success.md)).

`-n/--dry-run` (every command that changes files) prints the plan and returns before
any tool or backend is resolved: `input -> destination` for glados' tasks
(`print_plan`), each planned operation for the file commands'. The one exception is
`date-copy --from exif`, whose plan needs the dates, so `-n` runs exiftool to read
them (it writes nothing).

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
  -> Glados.backend("transcribe", Transcriber, -b, {"model": -m})
       config (lazy) -> backends.select -> backends.load -> e.g. WhisperCppBackend
  -> Job([AudioExtractor, TranscribeStep], dest = INPUT.<format> or -o)
       AudioExtractor: ffmpeg -> temp mono 16 kHz WAV
       TranscribeStep: Transcriber.transcribe -> segments -> FORMATTERS[format] -> temp file
  -> run_jobs: per input, run the Job and move its temp file to the destination
```

## Data flow (audio-grep)

```
audio-grep ARGUMENTS...
  -> split_command_line: existing dirs and audio/video files are inputs, the rest grep args
  -> inputs = expand_inputs(inputs, audio/video)
  -> run_batch: per input, CachedTranscripts.segments
       key = audio-grep/ + sha256(content sha256, mtime_ns, --backend, --model, --language)
       shared user cache (core/cache.py) hit -> segments
       miss -> Glados.backend("transcribe", ...) (first miss only)
            -> AudioExtractor -> Transcriber.transcribe -> segments -> cache
  -> grep_transcripts: FORMATTERS[--transcript-format] -> one temp file per input
       -> GrepRunner: grep GREP_ARGS TEMP... -> temp paths in its output replaced by media paths
  -> exit with grep's status, or 2 if an input failed
```

## Data flow (rewrite, summarize, expand, translate, describe)

```
rewrite PATH... -i INSTRUCTIONS
  -> inputs = expand_inputs(PATH..., text files except *.rewrite.*)
  -> prompt = config.prompts.render_rewrite(INSTRUCTIONS)     ([prompts] or default)
  -> Glados.backend("rewrite", Rewriter, -b, {"model": -m}) -> TextBackend
  -> Job([TextStep(text -> Rewriter.rewrite(text, prompt=prompt))],
         dest = INPUT.rewrite.<ext> or -o)
       TextStep: read UTF-8 -> transport.complete(prompt, text) streams the reply -> temp file
  -> run_jobs: per input, run the Job and move its temp file to the destination
```

`summarize` and `expand` have the same shape (`--max-length` / `--target-length` fill
the prompt's `{length}`; outputs `FILE.summary.<ext>`, `FILE.expanded.<ext>`). The LLM
backends are only `ChatTransport`s (one system prompt, one user message with optional
images, streamed reply); `lib/text_backend.py` wraps a transport into one
`TextBackend` that satisfies `Rewriter`, `Summarizer`, `Expander`, `Translator` and
`Describer`, and `text_plugin_triples()` returns it under
all of them. Prompts belong to the tasks, not to the backends.

`translate -l LANGUAGE` has the same shape too: the language fills `{language}` and,
through `lib/translate.language_infix`, names the output (`FILE.es.<ext>`).
`describe` takes images instead of text, and by default prints instead of writing:

```
describe PATH... -i INSTRUCTIONS [-l LANGUAGE] [-w | -o FILE]
  -> inputs = expand_inputs(PATH..., images)
  -> language = language_name(-l) or the system locale's (commands/describe.py reads it)
  -> prompt = config.prompts.render_describe(INSTRUCTIONS, language)  (appends "Reply in <language>.")
  -> Glados.backend_options("describe", -b, {"model": -m}) -> (backend, options), nothing loaded
  -> describer = CachedDescriber(shared cache, lazy Glados.backend("describe", ...))
       key = describe/ + sha256(image content sha256, prompt, backend, options minus api_key)
       hit -> text; miss -> TextBackend (built on the first miss) -> text -> cache
       (--no-cache: the TextBackend directly)
  default (a report):
  -> run_batch: describe_image -> transport.complete(prompt, "", images=[INPUT])
       -> consume_stream -> text
  -> print "INPUT: text" per image, then finish_batch
  -w or -o (a file producer; -y and -n apply only here):
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

## File commands

File commands have no backends, entry-point groups or config: they never take
`pass_glados`, so they never load the config. They use filejobs: `Job` and `run_jobs`
for every command that writes a file, plain functions under `run_batch` for reports,
renames and checks, and `cli_options` for `PATH...`, `-y` and `-n`; logging comes from
`cli_common.logging_options`, as for the tasks.

- Commands that change files (`jpgize`, `mp4ize`, `motionphotos`, `img-trim`,
  `img-reduce`, `img-embed-description`, `rename-by-hash`, `fix-extensions`, `date-copy`,
  `cleanup`) plan first (`plan_conversions`, `plan_merges`, `plan_captions`,
  `plan_rename`, `plan_extension_fix`, `dates.plan_change`, `cleanup.plan_cleanup`, or a
  destination per input), then apply, so `-n` prints the plan without touching anything
  or requiring the extra, and the external tools only for `date-copy --from exif`.
- `date-copy` reads every date first (a `dates.DateSource`, under one `run_batch`), then
  applies the planned `Rename`, `SetMtime` or `SetExifDate` changes under a second one.
  The command picks the source for `--from` (`MtimeDates`, `NameDates`, `ExifDates`,
  `ShotwellDates`), wrapped in `MtimeFallback` with `--mtime-fallback`. EXIF and
  QuickTime dates go through exiftool (`-api QuickTimeUTC`, so video dates are local
  time); Shotwell's exposure times come from its database, opened read-only. Shotwell is
  a source only. Dates are aware datetimes in the local zone.
- `cleanup` walks the trees itself (`cleanup.plan_cleanup`) instead of using
  `filejobs.inputs.expand_inputs`, since it removes and chmods directories as well as
  files; it does not descend into junk directories or follow symlinks.
- In-memory transforms (motion-photo join/split/strip) are `BytesStep`s; `jpgize` is
  `JpegConversionStep` (ImageMagick, then exiftool copies the tags except Orientation)
  and `mp4ize` is `Mp4RemuxStep` (ffmpeg through `filejobs/runners.py`, copying the video
  stream; the audio is copied or, failing that, re-encoded to AAC).
- `img-trim` and `img-reduce` are `BytesStep`s (Pillow, keeping EXIF and the ICC
  profile; lossy formats saved at quality 90); `img-reduce --in-place` lands the result
  on the input's own path. `img-embed-description` is `CaptionStep` (exiftool writes
  XMP-dc:Description and EXIF:ImageDescription into a copy, landed in place); an image
  without a `NAME.description.txt` (or with `--redescribe`) is first described by a
  `DescribeStep` Job landing the sidecar, through the same describer as `describe`.
- `img-hash`, `img-duplicates`, `img-check`, `img-trim` and `img-reduce` need the `images` extra
  (Pillow, pillow-heif); `glados.lib.imghash` and `glados.lib.imgedit` are imported
  through `load_extra_module` only when one of them runs. `img-hash` caches hashes in
  the shared cache (`img-hash/` keys: content digest and hash size).
- `img-check` is a report: the problems on stdout, exit 1 if there were any.

Boundaries ([decision 0011](decisions/0011-one-tool.md)): filejobs imports nothing
from glados; `glados.lib` imports none of `glados.core`, `glados.plugins` and
`glados.commands`; `glados.plugins` imports only `glados.lib`.
`tests/test_boundaries.py` checks them, and `tests/test_session.py` runs a file command
with a config loader that always fails.

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
- **File commands** are tested through their domain modules (`test_file_domain.py`),
  the conversion steps against fake executables (`test_conversions.py`), and the
  commands through click's `CliRunner` (`test_file_commands.py`, which also checks
  that no command declares an option twice). Their integration tests
  (`tests/test_file_integration.py`) run the real ImageMagick, exiftool and
  ffmpeg and skip when a tool is not on `PATH`; the image-hash tests skip without the
  `images` extra.
- **Boundaries** (`tests/test_boundaries.py`) parse the sources with `ast`: the
  import boundaries of filejobs, `glados.lib` and `glados.plugins`, and where click may
  be imported.

The OpenAI `whisper` backend has no tests yet.

## Configuration

`Glados.config()` (`core/session.py`) loads the config on first use (never at import): `.env`, then
`$XDG_CONFIG_HOME/glados/config.toml` with `${VAR}` expansion, validated into the frozen
`Config` model (`tasks`, `backends`, `prompts`) and checked against the installed
backends. A missing file is an empty config. A backend's options for a task are
`[backends.<name>]` with `[backends.<name>.tasks.<task>]` on top
(`Config.backend_options`, decision 0010).

## Console and logging

Both come from `foundation`:

- `progress.py` draws through `foundation.clilib.get_stderr_console()` and picks the
  rich or plain reporter from `RICH_STDERR_ENABLED`. Rich bars are transient; the plain
  reporter logs its lines at INFO on `filejobs.progress`, so they show only with `-v`.
- `cli_common.logging_options` adds `--log-level`/`-v`/`-q` to every command, after
  its name (`audio-grep`: `--log-level` only; the group takes none), and
  calls `foundation.loglib.setup_logger_from_click("glados", ...)`. Without flags the
  level comes from `GLADOS_LOG_LEVEL`, else `warning`. It is
  `cli_options.logging_options_for("glados")`. The shared `filejobs`
  logger gets the app logger's level, so `-v` and a bare `--log-level info` reach it
  (a bare level alone would only set the app logger); an explicit `filejobs:<level>`
  rule in `--log-level` wins. Modules log via
  `logging.getLogger(__name__)`; log records and progress bars share the stderr console.
