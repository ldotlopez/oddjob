# Whisper models

`transcribe` has two local backends, each with its own model format.

| Backend       | Model                                   | Default                                        |
| ------------- | --------------------------------------- | ---------------------------------------------- |
| `whisper`     | a model name, or a path to a `.pt` file | `turbo`                                        |
| `whisper_cpp` | a path to a ggml `.bin` file            | `default-model.bin` in the user data directory (`~/.local/share/whisper/` on Linux) |

Set the model with `-m`, or `model` under `[backends.whisper]` /
`[backends.whisper_cpp]` in the config.

## Choosing a model

- Sizes: `tiny`, `base`, `small`, `medium`, `large-v3`, and `turbo`
  (`large-v3-turbo` in whisper.cpp), a pruned `large-v3` that is much faster at
  similar accuracy.
- `.en` variants (`tiny.en` ... `medium.en`) are English-only and slightly better at
  English; use the multilingual ones for anything else.
- Larger is more accurate and slower. `small` or `turbo` is a sensible start.

## `whisper` (openai-whisper)

Nothing to download by hand: the `whisper` CLI fetches a named model on first use
and caches it in `~/.cache/whisper/`.

```bash
uv run oddjob transcribe -b whisper talk.mp4 -m small
```

To pre-fetch a model (e.g. before going offline), run `whisper` once with it on any
short audio file.

## `whisper_cpp` (ggml models)

Models are published in the `ggerganov/whisper.cpp` Hugging Face repository as
`ggml-<model>.bin`. Quantized variants (e.g. `ggml-large-v3-turbo-q5_0.bin`) are
smaller and faster, at a small accuracy cost. Catalog:
<https://huggingface.co/ggerganov/whisper.cpp/tree/main>.

```bash
mkdir -p ~/.local/share/whisper && cd ~/.local/share/whisper
curl -fLO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

`-f` makes curl fail on a 404 instead of saving an HTML error page as the model. A
whisper.cpp checkout also has `models/download-ggml-model.sh <model>`, which does
the same.

To use it without `-m`, link it under the default name:

```bash
ln -s ggml-small.bin ~/.local/share/whisper/default-model.bin
```

## Check

```bash
uv run oddjob transcribe -b whisper_cpp talk.mp4 -m ~/.local/share/whisper/ggml-small.bin
```
