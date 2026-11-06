# glados

CLI toolkit that applies model backends to files, one task per command.

| Task         | Status          | Input → output                                   |
| :----------- | :-------------- | :----------------------------------------------- |
| `transcribe` | implemented     | video/audio → `srt`, `vtt`, `txt`, `json`, `csv`, `lrc` |
| `rewrite`    | not implemented | text → `<name>.rewrite.<ext>`                    |
| `summarize`  | not implemented | text → `<name>.summary.<ext>`                    |
| `expand`     | not implemented | text → `<name>.expanded.<ext>`                   |

Backends: `whisper` (local whisper.cpp CLI) implements `transcribe`.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- For `transcribe` with `whisper`: `ffmpeg`, `ffprobe` and `whisper-cli` on `PATH`,
  and a ggml whisper model.

## Install

```sh
uv sync
```

## Usage

Every task runs as `glados <task> FILE ...` or as its own command (`transcribe FILE ...`).

```sh
uv run transcribe talk.mp4                    # -> talk.srt
uv run glados transcribe talk.mp4 -f vtt -l en
uv run transcribe talk.mp4 -m ~/models/ggml-small.bin -o subs/talk.srt -y
```

Common options:

| Option                  | Meaning                                                     |
| :---------------------- | :---------------------------------------------------------- |
| `-o, --output FILE`     | explicit destination (default: derived from the input name) |
| `-y, --overwrite`       | overwrite an existing destination                           |
| `-b, --backend NAME`    | backend for this task (also `GLADOS_<TASK>_BACKEND`)        |
| `-m, --model PATH`      | overrides the backend's `model` option                      |
| `-v` / `-q`             | more / less logging (repeatable)                            |
| `--log-level SPEC`      | e.g. `debug` or `glados.core:debug,*:info` (also `GLADOS_LOG_LEVEL`) |

`transcribe` also takes `-l, --language` (default: auto-detect) and `-f, --format`
(default: `srt`).

## Configuration

Optional, at `$XDG_CONFIG_HOME/glados/config.toml`. `${VAR}` placeholders are expanded
from the environment (and a `.env` file); write a literal `$` as `$$`.

```toml
[tasks]
transcribe = "whisper"          # backend per task

[backends.whisper]
model = "~/models/ggml-small.bin"
binary = "whisper-cli"
```

Backend selection: `-b`, then `GLADOS_<TASK>_BACKEND`, then `[tasks]`, then the only
installed backend. Backend options: the backend's defaults, then `[backends.<name>]`,
then CLI flags. The default whisper model is
`$XDG_DATA_HOME/whisper/default-model.bin`.

Progress is drawn as rich bars on a terminal and as plain percentage lines otherwise
(piped stderr, `TERM=dumb`, `RICH_DISABLED=1`).

## Development

```sh
uv run ruff check --fix . && uv run ruff format .
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout and how to add a
backend, and [docs/decisions/](docs/decisions/) for recorded decisions.
