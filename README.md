# glados

CLI toolkit that applies model backends to files, one task per command.

| Task         | Status          | Input → output                                   |
| :----------- | :-------------- | :----------------------------------------------- |
| `transcribe` | implemented     | video/audio → `srt`, `vtt`, `txt`, `json`, `csv`, `lrc` |
| `rewrite`    | not implemented | text → `<name>.rewrite.<ext>`                    |
| `summarize`  | not implemented | text → `<name>.summary.<ext>`                    |
| `expand`     | not implemented | text → `<name>.expanded.<ext>`                   |

Backends implementing `transcribe`: `whisper` (OpenAI's local `whisper` CLI) and
`whisper_cpp` (local whisper.cpp `whisper-cli`).

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- For `transcribe`: `ffmpeg` and `ffprobe` on `PATH`, plus the backend's CLI:
  - `whisper`: `whisper` from [openai-whisper](https://github.com/openai/whisper)
    (`uv tool install openai-whisper`); models are downloaded by name on first use.
  - `whisper_cpp`: `whisper-cli` from whisper.cpp and a ggml whisper model.

## Install

```sh
uv sync
```

## Usage

Every task runs as `glados <task> FILE ...` or as its own command (`transcribe FILE ...`).

```sh
uv run transcribe talk.mp4                    # -> talk.srt (backend from [tasks])
uv run glados transcribe -b whisper talk.mp4 -f vtt -l en -m small
uv run transcribe -b whisper_cpp talk.mp4 -m ~/models/ggml-small.bin -o subs/talk.srt -y
```

Common options:

| Option                  | Meaning                                                     |
| :---------------------- | :---------------------------------------------------------- |
| `-o, --output FILE`     | explicit destination (default: derived from the input name) |
| `-y, --overwrite`       | overwrite an existing destination                           |
| `-b, --backend NAME`    | backend for this task (also `GLADOS_<TASK>_BACKEND`)        |
| `-m, --model MODEL`     | overrides the backend's `model` option (name or path)       |
| `-v` / `-q`             | more / less logging (repeatable)                            |
| `--log-level SPEC`      | e.g. `debug` or `glados.core:debug,*:info` (also `GLADOS_LOG_LEVEL`) |

`transcribe` also takes `-l, --language` (default: auto-detect) and `-f, --format`
(default: `srt`).

## Configuration

Optional, at `$XDG_CONFIG_HOME/glados/config.toml`. `${VAR}` placeholders are expanded
from the environment (and a `.env` file); write a literal `$` as `$$`.

```toml
[tasks]
transcribe = "whisper_cpp"      # backend per task

[backends.whisper]              # OpenAI whisper CLI
model = "turbo"                 # model name, or path to a .pt checkpoint
binary = "whisper"

[backends.whisper_cpp]          # whisper.cpp
model = "~/models/ggml-small.bin"
binary = "whisper-cli"
```

Backend selection: `-b`, then `GLADOS_<TASK>_BACKEND`, then `[tasks]`, then the only
installed backend; with both whisper backends installed, `transcribe` needs one of
those. Backend options: the backend's defaults, then `[backends.<name>]`, then CLI
flags. Default models: `turbo` for `whisper`, `$XDG_DATA_HOME/whisper/default-model.bin`
for `whisper_cpp`.

`whisper` used to name the whisper.cpp backend; that one is now `whisper_cpp`. Move
existing `[backends.whisper]` settings for whisper.cpp to `[backends.whisper_cpp]`.

Progress is drawn as rich bars on a terminal and as plain percentage lines otherwise
(piped stderr, `TERM=dumb`, `RICH_DISABLED=1`).

## Development

```sh
uv run ruff check --fix . && uv run ruff format .
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout and how to add a
backend, and [docs/decisions/](docs/decisions/) for recorded decisions.
