# glados

CLI toolkit that applies model backends to files, one task per command. The same
distribution also installs [`multitool`](#multitool), file utilities with no
backends.

| Task         | Status          | Input → output                                   |
| :----------- | :-------------- | :----------------------------------------------- |
| `transcribe` | implemented     | video/audio → `txt`, `srt`, `vtt`, `json`, `csv`, `lrc` |
| `rewrite`    | implemented     | text → `<name>.rewrite.<ext>`                    |
| `summarize`  | implemented     | text → `<name>.summary.<ext>`                    |
| `expand`     | implemented     | text → `<name>.expanded.<ext>`                   |
| `translate`  | implemented     | text → `<name>.<language>.<ext>`                 |
| `describe`   | implemented     | image → `<name>.description.txt` (needs a model that takes images) |

Backends:

| Backend       | Tasks                         | What it runs                                       |
| :------------ | :---------------------------- | :------------------------------------------------- |
| `whisper`     | transcribe                    | OpenAI's local `whisper` CLI (openai-whisper)      |
| `whisper_cpp` | transcribe                    | local whisper.cpp `whisper-cli`                    |
| `openai`      | the text tasks¹               | OpenAI Chat Completions API, or any compatible server |
| `ollama`      | the text tasks¹               | Ollama's native API (`/api/chat`)                  |
| `llm`         | the text tasks¹               | the [`llm`](https://llm.datasette.io) CLI          |

¹ rewrite, summarize, expand, translate and describe.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- For `transcribe`: `ffmpeg` and `ffprobe` on `PATH`, plus the backend's CLI:
  - `whisper`: `whisper` from [openai-whisper](https://github.com/openai/whisper)
    (`uv tool install openai-whisper`); models are downloaded by name on first use.
  - `whisper_cpp`: `whisper-cli` from whisper.cpp and a ggml whisper model.
- For the text tasks, the backend's service or CLI:
  - `openai`: an API key (`OPENAI_API_KEY`, or `api_key`) for OpenAI, or the
    `base_url` of an OpenAI-compatible server.
  - `ollama`: a running Ollama server (default `http://localhost:11434`), plus an
    `api_key` if it needs one (ollama.com, or a server behind an authenticating proxy).
  - `llm`: `llm` on `PATH`, with its own keys and plugins configured.
- `describe`: a backend model that takes images (e.g. `gpt-4.1-mini`, or an Ollama
  vision model such as `llama3.2-vision` via `-m`).
- For multitool: ImageMagick (`magick` or `convert`) and `exiftool` for `jpgize`,
  `exiftool` for `img-caption`, `ffmpeg`/`ffprobe` for `mp4ize`, and the `multitool`
  extra (Pillow, pillow-heif) for `img-hash`, `img-duplicates`, `img-check` and
  `autocrop`.

## Install

```sh
uv sync                       # glados
uv sync --extra multitool     # also multitool's Pillow-based image commands
```

## Usage

Every task runs as `glados <task> PATH...` or as its own command (`transcribe PATH...`).
`PATH` may be a file or a directory; directories are walked recursively for the files
the task handles (audio/video for `transcribe`, text files for the others, skipping
the task's own earlier outputs), and each file gets its own output next to it. If an
input fails, the rest still run and the command exits 1 at the end.

```sh
uv run transcribe talk.mp4                    # -> talk.txt (backend from [tasks])
uv run transcribe lectures/ extra.m4a         # every audio/video file under lectures/, plus extra.m4a
uv run rewrite -n notes/                      # print input -> destination, change nothing
uv run glados transcribe -b whisper talk.mp4 -f vtt -l en -m small
uv run transcribe -b whisper_cpp talk.mp4 -m ~/models/ggml-small.bin -o subs/talk.srt -y   # SRT, from -o
uv run rewrite -b ollama notes.md -i "more formal tone"   # -> notes.rewrite.md
uv run glados summarize -b openai report.txt --max-length 200
uv run expand -b llm -m gpt-4o-mini outline.md --target-length 800
```

Common options:

| Option                  | Meaning                                                     |
| :---------------------- | :---------------------------------------------------------- |
| `-o, --output FILE`     | explicit destination, only with a single input file (default: derived from the input name) |
| `-y, --overwrite`       | overwrite an existing destination                           |
| `-n, --dry-run`         | print `input -> destination` per input; resolve no backend, write nothing |
| `-b, --backend NAME`    | backend for this task (also `GLADOS_<TASK>_BACKEND`)        |
| `-m, --model MODEL`     | overrides the backend's `model` option (name or path)       |
| `-v` / `-q`             | more / less logging (repeatable); `-v` shows progress lines and `wrote <dest>` |
| `--log-level SPEC`      | e.g. `debug` or `glados.core:debug,*:info` (also `GLADOS_LOG_LEVEL`) |

`transcribe` also takes `-l, --language` (default: auto-detect) and `-f, --format`
(default: the `-o` extension if it is a known format, else `txt`). `rewrite` takes
`-i, --instructions`; `summarize` takes `--max-length` and `expand`
`--target-length`, both approximate word counts. `translate` needs `-l, --language`
(e.g. `es`, `Brazilian Portuguese`), which also names its output; `describe` takes
`-i, --instructions` (e.g. `in Spanish`).

## Configuration

Optional, at `$XDG_CONFIG_HOME/glados/config.toml`. `${VAR}` placeholders are expanded
from the environment (and a `.env` file); write a literal `$` as `$$`.

```toml
[tasks]
transcribe = "whisper_cpp"      # backend per task
rewrite = "ollama"
summarize = "openai"

[backends.whisper]              # OpenAI whisper CLI
model = "turbo"                 # model name, or path to a .pt checkpoint
binary = "whisper"

[backends.whisper_cpp]          # whisper.cpp
model = "~/models/ggml-small.bin"
binary = "whisper-cli"

[backends.openai]               # also any OpenAI-compatible server
model = "gpt-4.1-mini"
base_url = "https://api.openai.com/v1"
# api_key defaults to the OPENAI_API_KEY environment variable
timeout = 600

[backends.ollama]
model = "llama3.2"
base_url = "http://localhost:11434"
options = { num_ctx = 8192 }    # passed through as Ollama model options
# api_key = "${OLLAMA_API_KEY}" # optional, sent as `Authorization: Bearer <key>`
timeout = 600

[backends.llm]
model = "gpt-4o-mini"           # unset: llm's own default model
binary = "llm"

[prompts]                       # system prompts of the text tasks, for every backend
summarize = "Summarize the text the user sends as bullet points. {length}"
```

`[prompts]` overrides the default prompt of `rewrite`, `summarize`, `expand`,
`translate` or `describe`. Each may use only its own placeholder: `{instructions}` in
`rewrite` and `describe`, `{length}` in `summarize` and `expand`, `{language}` in
`translate`; a literal brace is `{{` or `}}`.

Backend selection: `-b`, then `GLADOS_<TASK>_BACKEND`, then `[tasks]`, then the only
installed backend; with several backends installed for a task (both whisper ones for
`transcribe`, or the three text backends), that task needs one of those. Backend options: the backend's defaults, then `[backends.<name>]`, then CLI
flags. Default models: `turbo` for `whisper`, `$XDG_DATA_HOME/whisper/default-model.bin`
for `whisper_cpp`.

`whisper` used to name the whisper.cpp backend; that one is now `whisper_cpp`. Move
existing `[backends.whisper]` settings for whisper.cpp to `[backends.whisper_cpp]`.

Commands print nothing on success. Progress is drawn as transient rich bars on a
terminal; otherwise (piped stderr, `TERM=dumb`, `RICH_DISABLED=1`) it is logged as
percentage lines at INFO, shown with `-v`.

## multitool

File utilities without backends or config, run as `multitool <command>`:

| Command                     | What it does                                                          |
| :-------------------------- | :-------------------------------------------------------------------- |
| `sidecars scan PATH...`     | list groups of files sharing a name (`-e jpg -e mp4`: only groups with all of them) |
| `sidecars find FILE`        | list the sidecar files of FILE                                        |
| `motionphotos check FILE`   | exit 0 if FILE is a motion photo, 1 if not                            |
| `motionphotos join/split/strip` | build a motion photo from a JPEG and an MP4, take one apart, or drop its video |
| `motionphotos merge PATH...`| merge each `NAME.jpg` + `NAME.mp4` pair into `NAME.jpg` (`--rm`: remove the video) |
| `jpgize PATH...`            | HEIC/HEIF/WebP/PNG → JPEG, upright, keeping metadata and timestamps (`--rm`: remove sources) |
| `mp4ize PATH...`            | remux videos into MP4 without re-encoding the video (`--rm`: remove sources) |
| `img-hash PATH...`          | print each image's average hash (cached; `--no-cache`)                |
| `img-duplicates PATH...`    | groups of near-duplicate images (`--max-distance`, `-x CMD` per group) |
| `img-check PATH...`         | list the images that cannot be fully decoded, with the reason (exit 1 if any) |
| `autocrop PATH...`          | crop images to their non-transparent pixels → `NAME.cropped.<ext>`     |
| `img-caption PATH...`       | write each `NAME.description.txt` (from `glados describe`) into the image's XMP and EXIF description |
| `hash-rename PATH...`       | rename each file to `<digest of its content>.<ext>` (`--algo`)        |
| `fix-extensions PATH...`    | lowercase extensions; `jpeg` → `jpg`, `mpeg` → `mpg`, `tif` → `tiff`  |
| `srt-grep PATTERN PATH...`  | cues containing PATTERN in `.srt` files (a media file means its `NAME.srt`; exit 1 if none) |

```sh
uv run multitool jpgize -n ~/Pictures/import     # print the planned conversions
uv run multitool motionphotos merge --rm ~/DCIM
uv run multitool img-duplicates ~/Pictures -x "echo"
```

Commands that change files (`jpgize`, `mp4ize`, `motionphotos merge`, `autocrop`,
`img-caption`, `hash-rename`, `fix-extensions`) take `-n/--dry-run`; commands that would
replace an existing file need `-y/--overwrite`, and `img-caption` always does (it
writes in place). `img-hash`, `img-duplicates`, `img-check` and `autocrop` need the
`multitool` extra (`uv sync --extra multitool`). `img-caption` pairs with
`glados describe`, and `srt-grep` with `glados transcribe -f srt`. Commands taking `PATH...`
keep going when one input fails (exit 1 at the end); on success, commands that write
files print nothing (`-v` logs `wrote <dest>` for each). Logging options (`-v`, `-q`, `--log-level`, `MULTITOOL_LOG_LEVEL`) go before the
command: `multitool -v jpgize ...`.

## Development

```sh
uv sync --extra multitool     # so the image-hash tests run
uv run ruff check --fix . && uv run ruff format .
uv run python -m unittest discover -s tests -v
```

Unit tests use fake executables and a local fake HTTP server, so they need no services.
Each backend also has an integration test against the real thing (`whisper-cli`, `llm`,
an Ollama server, an OpenAI-compatible API), skipped until it is configured: copy
`tests/integration.env.example` to `tests/integration.env` (git-ignored, it holds
secrets) and fill in the backends to test. `GLADOS_TEST_*` environment variables
override the file. multitool's integration tests run the real ImageMagick, exiftool
and ffmpeg, and skip when they are not on `PATH`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout and how to add a
backend, and [docs/decisions/](docs/decisions/) for recorded decisions.

## Roadmap

- **whisper.cpp on the AMD Ryzen AI NPU.** whisper.cpp ≥ 1.9 can offload the encoder
  to the XDNA NPU via VitisAI (`-DWHISPER_VITISAI=1`); no glados change is needed,
  only the host setup:
  - `amdxdna` kernel driver (mainline since 6.14, or AMD's out-of-tree `xdna-driver`)
    and the NPU firmware for the chip revision (`/usr/lib/firmware/amdnpu/17f0_20`);
  - XRT (`xrt-smi examine` must list the NPU) and FlexML runtime, both sourced
    before building and running;
  - rebuild whisper.cpp with `-DWHISPER_VITISAI=1`, and fetch each model's
    `.rai` encoder cache with `models/download-vitisai-model.sh <model>`;
  - verify: `whisper-cli` prints `VITISAI = 1` and logs the offload mode.

  Cheaper interim step: build with `-DGGML_VULKAN=1` to use the integrated GPU.
