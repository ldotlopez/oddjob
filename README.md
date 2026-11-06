# glados

CLI toolkit that applies model backends to files, one task per command.

| Task         | Status          | Input → output                                   |
| :----------- | :-------------- | :----------------------------------------------- |
| `transcribe` | implemented     | video/audio → `srt`, `vtt`, `txt`, `json`, `csv`, `lrc` |
| `rewrite`    | implemented     | text → `<name>.rewrite.<ext>`                    |
| `summarize`  | implemented     | text → `<name>.summary.<ext>`                    |
| `expand`     | implemented     | text → `<name>.expanded.<ext>`                   |

Backends:

| Backend       | Tasks                         | What it runs                                       |
| :------------ | :---------------------------- | :------------------------------------------------- |
| `whisper`     | transcribe                    | OpenAI's local `whisper` CLI (openai-whisper)      |
| `whisper_cpp` | transcribe                    | local whisper.cpp `whisper-cli`                    |
| `openai`      | rewrite, summarize, expand    | OpenAI Chat Completions API, or any compatible server |
| `ollama`      | rewrite, summarize, expand    | Ollama's native API (`/api/chat`)                  |
| `llm`         | rewrite, summarize, expand    | the [`llm`](https://llm.datasette.io) CLI          |

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
uv run rewrite -b ollama notes.md -i "more formal tone"   # -> notes.rewrite.md
uv run glados summarize -b openai report.txt --max-length 200
uv run expand -b llm -m gpt-4o-mini outline.md --target-length 800
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
(default: `srt`). `rewrite` takes `-i, --instructions`; `summarize` takes
`--max-length` and `expand` `--target-length`, both approximate word counts.

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

`[prompts]` overrides the default prompt of `rewrite`, `summarize` or `expand`. Each
may use only its own placeholder: `{instructions}` in `rewrite`, `{length}` in
`summarize` and `expand`; a literal brace is `{{` or `}}`.

Backend selection: `-b`, then `GLADOS_<TASK>_BACKEND`, then `[tasks]`, then the only
installed backend; with several backends installed for a task (both whisper ones for
`transcribe`, or the three text backends), that task needs one of those. Backend options: the backend's defaults, then `[backends.<name>]`, then CLI
flags. Default models: `turbo` for `whisper`, `$XDG_DATA_HOME/whisper/default-model.bin`
for `whisper_cpp`.

`whisper` used to name the whisper.cpp backend; that one is now `whisper_cpp`. Move
existing `[backends.whisper]` settings for whisper.cpp to `[backends.whisper_cpp]`.

Progress is drawn as rich bars on a terminal and as plain percentage lines otherwise
(piped stderr, `TERM=dumb`, `RICH_DISABLED=1`).

## Development

```sh
uv run ruff check --fix . && uv run ruff format .
uv run python -m unittest discover -s tests -v
```

Unit tests use fake executables and a local fake HTTP server, so they need no services.
Each backend also has an integration test against the real thing (`whisper-cli`, `llm`,
an Ollama server, an OpenAI-compatible API), skipped until it is configured: copy
`tests/integration.env.example` to `tests/integration.env` (git-ignored, it holds
secrets) and fill in the backends to test. `GLADOS_TEST_*` environment variables
override the file.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module layout and how to add a
backend, and [docs/decisions/](docs/decisions/) for recorded decisions.
