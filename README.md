# oddjob

[![CI](https://github.com/ldotlopez/oddjob/actions/workflows/ci.yml/badge.svg)](https://github.com/ldotlopez/oddjob/actions/workflows/ci.yml)
[![Release workflow](https://github.com/ldotlopez/oddjob/actions/workflows/release.yml/badge.svg)](https://github.com/ldotlopez/oddjob/actions/workflows/release.yml)
[![Release](https://img.shields.io/github/v/release/ldotlopez/oddjob?include_prereleases)](https://github.com/ldotlopez/oddjob/releases)
[![License](https://img.shields.io/github/license/ldotlopez/oddjob)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-zepolson-FFDD00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/zepolson)

CLI toolkit for files, one command each, all under `oddjob`: tasks that go through
replaceable model backends (below), and [file commands](#file-commands) with no
backends or config. `oddjob --help` lists them by subject.

| Task         | Status          | Input → output                                   |
| :----------- | :-------------- | :----------------------------------------------- |
| `transcribe` | implemented     | video/audio → `txt`, `srt`, `vtt`, `json`, `csv`, `lrc` |
| `speak`      | implemented     | text files, `--text` or stdin → `<name>.wav` (`-o` for text and stdin) |
| `rewrite`    | implemented     | text → `<name>.rewrite.<ext>`                    |
| `summarize`  | implemented     | text → `<name>.summary.<ext>`                    |
| `expand`     | implemented     | text → `<name>.expanded.<ext>`                   |
| `translate`  | implemented     | text → `<name>.<language>.<ext>`                 |
| `describe`   | implemented     | image → description on stdout, or `<name>.description.txt` with `-w` (needs a model that takes images) |
| `audio-grep` | implemented     | video/audio → grep's output over the transcriptions, on stdout (uses the `transcribe` backends) |

Backends:

| Backend       | Tasks                         | What it runs                                       |
| :------------ | :---------------------------- | :------------------------------------------------- |
| `whisper`     | transcribe                    | OpenAI's local `whisper` CLI (openai-whisper)      |
| `whisper_cpp` | transcribe                    | local whisper.cpp `whisper-cli`                    |
| `piper`       | speak                         | local `piper` CLI ([piper-tts](https://github.com/OHF-Voice/piper1-gpl)) |
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
- For `speak`: `piper` from piper-tts on `PATH` and a voice `.onnx` file (its `.json`
  beside it), set with `-m` or `[backends.piper] model`.
- For the text tasks, the backend's service or CLI:
  - `openai`: an API key (`OPENAI_API_KEY`, or `api_key`) for OpenAI, or the
    `base_url` of an OpenAI-compatible server.
  - `ollama`: a running Ollama server (default `http://localhost:11434`), plus an
    `api_key` if it needs one (ollama.com, or a server behind an authenticating proxy).
  - `llm`: `llm` on `PATH`, with its own keys and plugins configured.
- `describe`: a backend model that takes images (e.g. `gpt-4.1-mini`, or an Ollama
  vision model such as `llama3.2-vision` via `-m`).
- For the file commands: ImageMagick (`magick` or `convert`) and `exiftool` for `jpgize`,
  `exiftool` for `img-embed-description`, `photo-lint` and `date-copy` with `exif`, `ffmpeg`/`ffprobe` for
  `mp4ize`, and the `images` extra (Pillow, pillow-heif) for `img-hash`,
  `img-duplicates`, `img-check`, `img-trim` and `img-reduce`.

## Install

```sh
uv sync                       # oddjob
uv sync --extra images        # also the Pillow-based image commands
```

## Usage

Every task runs as `oddjob <task> PATH...`.
`PATH` may be a file or a directory; directories are walked recursively for the files
the task handles (audio/video for `transcribe`, text files for the others, skipping
the task's own earlier outputs), and each file gets its own output next to it. If an
input fails, the rest still run and the command exits 1 at the end.

```sh
uv run oddjob transcribe talk.mp4             # -> talk.txt (backend from [tasks])
uv run oddjob transcribe lectures/ extra.m4a  # every audio/video file under lectures/, plus extra.m4a
uv run oddjob rewrite -n notes/               # print input -> destination, change nothing
uv run oddjob transcribe -b whisper talk.mp4 -f vtt -l en -m small
uv run oddjob transcribe -b whisper_cpp talk.mp4 -m ~/models/ggml-small.bin -o subs/talk.srt -y   # SRT, from -o
uv run oddjob rewrite -b ollama notes.md -i "more formal tone"   # -> notes.rewrite.md
uv run oddjob summarize -b openai report.txt --max-length 200
uv run oddjob expand -b llm -m gpt-4o-mini outline.md --target-length 800
```

Common options:

| Option                  | Meaning                                                     |
| :---------------------- | :---------------------------------------------------------- |
| `-o, --output FILE`     | explicit destination, only with a single input file (default: derived from the input name) |
| `-y, --overwrite`       | overwrite an existing destination                           |
| `-n, --dry-run`         | print `input -> destination` per input; resolve no backend, write nothing |
| `-b, --backend NAME`    | backend for this task (also `ODDJOB_<TASK>_BACKEND`)        |
| `-m, --model MODEL`     | overrides the backend's `model` option (name or path)       |
| `-v` / `-q`             | more / less logging (repeatable); `-v` shows progress lines and `wrote <dest>` |
| `--log-level SPEC`      | e.g. `debug` or `oddjob.core:debug,*:info` (also `ODDJOB_LOG_LEVEL`) |

`transcribe` also takes `-l, --language` (default: auto-detect) and `-f, --format`
(default: the `-o` extension if it is a known format, else `txt`). `rewrite` takes
`-i, --instructions`; `summarize` takes `--max-length` and `expand`
`--target-length`, both approximate word counts. `translate` needs `-l, --language`
(e.g. `es`, `Brazilian Portuguese`), which also names its output. `describe` prints
`PATH: description` per image; `-w, --write` (implied by `-o`) writes
`<name>.description.txt` instead, and `-y`/`-n` apply only then. It also takes
`-i, --instructions` and `-l, --language` (e.g. `es`, `Brazilian Portuguese`); without
`-l` the description is requested in the language of the system locale (`LC_ALL`,
`LC_MESSAGES`, `LANG`), and in no particular language under `C`/`POSIX` or an unset locale.
Descriptions are cached; `--no-cache` skips it.

`speak` voices text as WAV audio. Its text comes from text files (`PATH...`, each
written next to itself as `<name>.wav`), from `-t, --text TEXT`, or from stdin (`-`, or
a pipe when nothing else is given; a pipe is ignored if `PATH...` or `--text` is given).
Text and stdin have no name to derive a destination from, so they need `-o`. `--speaker N`
picks a voice of a multi-speaker model.

```sh
uv run oddjob speak notes.txt                       # -> notes.wav
uv run oddjob speak -t "Hello there" -o hello.wav
echo "Hello there" | uv run oddjob speak -o hello.wav
```

`audio-grep` runs the system `grep` over the transcriptions of audio/video files:

```sh
uv run oddjob audio-grep -i -n budget talks/ meeting.mp4   # talks/q3.mp4:4:[01:02.30]the budget for Q3
```

Arguments that are existing directories or audio/video files are the inputs; every
other argument goes to grep unchanged, and grep's output names the media files. Its
own options are long-only, since grep owns the short ones: `--backend`, `--model`,
`--language`, `--transcript-format` (what grep searches, default `lrc`: one
timestamped line per segment) and `--log-level`. A pattern starting with `-` needs
`-e`. Exit status is grep's, or 2 if a file could not be transcribed. No sidecar is
written: transcripts go to the shared cache (see below), keyed by a digest of the
file's content, its mtime and `--backend`/`--model`/`--language`, so the cache holds
no paths.

### Cache

`audio-grep`, `describe`, `img-hash` and `img-duplicates` share one cache in
`$XDG_CACHE_HOME/oddjob`, owner-only, with keys `<command>/<digest>`. Entries expire
after 180 days, and the least recently used are dropped when the cache passes 1 GiB
(checked once a day). `describe` keys on the image's content, the prompt, the backend
and its configured options (not `api_key`); `img-hash` on the content and `--hash-size`.
`describe` and the hash commands take `--no-cache`. The cache can be deleted at any
time.

## Configuration

Optional, at `$XDG_CONFIG_HOME/oddjob/config.toml`. `${VAR}` placeholders are expanded
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

[backends.piper]                # piper-tts
model = "~/voices/en_US-lessac-medium.onnx"
binary = "piper"

[backends.openai]               # also any OpenAI-compatible server
model = "gpt-4.1-mini"
base_url = "https://api.openai.com/v1"
# api_key defaults to the OPENAI_API_KEY environment variable
timeout = 600

[backends.openai.tasks.describe]  # on top of [backends.openai], for describe only
model = "gpt-4.1"                 # describe needs a vision model

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

Backend selection: `-b`, then `ODDJOB_<TASK>_BACKEND`, then `[tasks]`, then the only
installed backend; with several backends installed for a task (both whisper ones for
`transcribe`, or the three text backends), that task needs one of those. Backend options: the backend's defaults, then `[backends.<name>]`, then
`[backends.<name>.tasks.<task>]` (only when that backend runs that task), then CLI
flags. Default models: `turbo` for `whisper`, `$XDG_DATA_HOME/whisper/default-model.bin`
for `whisper_cpp`.

`whisper` used to name the whisper.cpp backend; that one is now `whisper_cpp`. Move
existing `[backends.whisper]` settings for whisper.cpp to `[backends.whisper_cpp]`.

Commands print nothing on success. Progress is drawn as transient rich bars on a
terminal; otherwise (piped stderr, `TERM=dumb`, `RICH_DISABLED=1`) it is logged as
percentage lines at INFO, shown with `-v`.

## File commands

File utilities without backends or config, run as `oddjob <command>`:

| Command                     | What it does                                                          |
| :-------------------------- | :-------------------------------------------------------------------- |
| `sidecars scan PATH...`     | list groups of files sharing a name (`-e jpg -e mp4`: only groups with all of them) |
| `sidecars find FILE`        | list the sidecar files of FILE                                        |
| `motionphotos check FILE`   | exit 0 if FILE is a motion photo, 1 if not                            |
| `motionphotos join/split/strip` | build a motion photo from a JPEG and an MP4 (`-i IMAGE --video VIDEO`), take one apart, or drop its video (`strip` → `NAME.still.jpg`; `--in-place`: replace FILE) |
| `motionphotos merge PATH...`| merge each `NAME.jpg` + `NAME.mp4` pair into `NAME.motion.jpg` (`--in-place`: into `NAME.jpg`; `--rm`: remove the video) |
| `jpgize PATH...`            | HEIC/HEIF/WebP/PNG → JPEG, upright, keeping metadata and timestamps (`--rm`: remove sources) |
| `mp4ize PATH...`            | remux videos into MP4 without re-encoding the video (`--rm`: remove sources) |
| `img-hash PATH...`          | print each image's average hash (cached by content; `--no-cache`)    |
| `img-duplicates PATH...`    | groups of near-duplicate images (`--max-distance`, `-x CMD` per group) |
| `img-check PATH...`         | list the images that cannot be fully decoded, with the reason (exit 1 if any) |
| `img-trim PATH...`          | crop images to their non-transparent pixels → `NAME.cropped.<ext>`     |
| `img-reduce PATH...`        | downscale images whose longest side exceeds `--max-size` (2160) → `NAME.reduced.<ext>` (`--in-place`: replace the original) |
| `img-embed-description PATH...` | write each `NAME.description.txt` into the image's XMP and EXIF description → `NAME.described.<ext>` (`--in-place`: replace the original; `--keep-mtime`); images without one are described first (`--redescribe`: all of them) |
| `photo-lint check PATH...`  | list the images failing a metadata check, as `PATH: CODE` (`no-zone`: an EXIF capture date without a UTC offset; exit 1 if any) |
| `photo-lint set-zone PATH...` | record the UTC offset `--zone` (an IANA name, e.g. `Europe/Madrid`) had at each EXIF date's wall-clock time in `OffsetTime*` → `NAME.fixed.<ext>` (`--in-place`: replace the original; `--keep-mtime`); offsets already there are kept (`--replace-offsets`: rewrite them); a time the zone skips fails |
| `rename-by-hash PATH...`       | rename each file to `<digest of its content>.<ext>` (`--algo`)        |
| `fix-extensions PATH...`    | lowercase extensions; `jpeg` → `jpg`, `mpeg` → `mpg`, `tif` → `tiff`  |
| `date-copy PATH...`         | copy each image's or video's date `--from` exif/mtime/name/shotwell `--to` exif/mtime/name; `--to name` renames to `YYYY-mm-dd HH.MM.SS <crc32>.<ext>`; `--to exif` writes `NAME.dated.<ext>` (`--in-place`: replace the original; `--keep-mtime`) (`--name-format`, `--shotwell-db`, `--mtime-fallback`) |
| `cleanup PATH...`        | remove macOS, Windows and KDE leftovers (`.DS_Store`, `._NAME`, `Thumbs.db`, `.Trash-<uid>`...); `--perms`: chmod files 644, directories 755 |

```sh
uv run oddjob jpgize -n ~/Pictures/import     # print the planned conversions
uv run oddjob motionphotos merge --in-place --rm ~/DCIM
uv run oddjob img-duplicates ~/Pictures -x "echo"
```

Commands that change files (`jpgize`, `mp4ize`, `motionphotos merge`, `img-trim`,
`img-reduce`, `img-embed-description`, `photo-lint set-zone`, `rename-by-hash`, `fix-extensions`, `date-copy`, `cleanup`)
take `-n/--dry-run`. A command whose output already exists fails for that input;
`-y/--overwrite` replaces the output, never the input. Only `--in-place` replaces the
input itself (it implies `-y`); no command changes its input without it (decision 0013).
`img-hash`, `img-duplicates`, `img-check`, `img-trim` and `img-reduce` need the
`images` extra (`uv sync --extra images`). `img-embed-description` calls the `describe` backend for images without a
`NAME.description.txt`. Commands taking `PATH...`
keep going when one input fails (exit 1 at the end); on success, commands that write
files print nothing (`-v` logs `wrote <dest>` for each). Logging options (`-v`, `-q`,
`--log-level`, `ODDJOB_LOG_LEVEL`) are the same as the tasks' and go after the command
name: `oddjob jpgize -v ...`.

## Development

```sh
uv sync --extra images        # so the image-hash tests run
uv run ruff check --fix . && uv run ruff format .
uv run python -m unittest discover -s tests -v
```

Unit tests use fake executables and a local fake HTTP server, so they need no services.
Each backend also has an integration test against the real thing (`whisper-cli`, `llm`,
an Ollama server, an OpenAI-compatible API), skipped until it is configured: copy
`tests/integration.env.example` to `tests/integration.env` (git-ignored, it holds
secrets) and fill in the backends to test. `ODDJOB_TEST_*` environment variables
override the file. The file commands' integration tests run the real ImageMagick, exiftool
and ffmpeg, and skip when they are not on `PATH`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout and how to add a
backend, and [docs/decisions/](docs/decisions/) for recorded decisions.

### Releasing

A `vX.Y.Z` tag runs `.github/workflows/release.yml`: it checks the tag against
`[project].version`, runs the tests, builds the sdist and wheel and attaches them to a
GitHub release. Before tagging:

1. Point `foundation` in `pyproject.toml` at the commit of
   [foundation](https://github.com/ldotlopez/foundation) to ship with
   (`git ls-remote https://github.com/ldotlopez/foundation main` for the latest), then
   `uv lock && uv sync --all-extras` and run the tests. The wheel installs exactly that
   commit.
2. Bump `[project].version`, commit, and tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

## Roadmap

- **whisper.cpp on the AMD Ryzen AI NPU.** whisper.cpp ≥ 1.9 can offload the encoder
  to the XDNA NPU via VitisAI (`-DWHISPER_VITISAI=1`); no oddjob change is needed,
  only the host setup:
  - `amdxdna` kernel driver (mainline since 6.14, or AMD's out-of-tree `xdna-driver`)
    and the NPU firmware for the chip revision (`/usr/lib/firmware/amdnpu/17f0_20`);
  - XRT (`xrt-smi examine` must list the NPU) and FlexML runtime, both sourced
    before building and running;
  - rebuild whisper.cpp with `-DWHISPER_VITISAI=1`, and fetch each model's
    `.rai` encoder cache with `models/download-vitisai-model.sh <model>`;
  - verify: `whisper-cli` prints `VITISAI = 1` and logs the offload mode.

  Cheaper interim step: build with `-DGGML_VULKAN=1` to use the integrated GPU.

## License

GPL-3.0-or-later (see `LICENSE`).
