# Piper voices

`speak` (backend `piper`) needs a voice: an `.onnx` model plus its `.onnx.json`
config, side by side and with matching names. Piper refuses to load a model whose
`.onnx.json` is missing.

oddjob takes a path to the `.onnx` file, not a voice name: `-m`, or
`[backends.piper] model` in the config. Without either it uses
`default-voice.onnx` in the user data directory (`~/.local/share/piper/` on Linux).

Piper is developed at [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl);
the original `rhasspy/piper` repository is archived, and guides for its standalone
tarball binary are outdated.

## Choosing a voice

- Voices are named `<lang_REGION>-<name>-<quality>`, e.g. `en_US-lessac-medium`.
- Quality tiers: `x_low`, `low`, `medium`, `high`. `medium` (~60 MB) is the usual
  balance of size and naturalness.
- Catalog: <https://huggingface.co/rhasspy/piper-voices/tree/main>. Samples to
  listen before downloading: <https://rhasspy.github.io/piper-samples/>.

## Download with piper's downloader

`piper.download_voices` must run with the interpreter that has `piper-tts`
installed; any other gives `No module named piper`. With
`uv tool install piper-tts`, that is the tool's own venv:

```bash
PIPER_PY="$(uv tool dir)/piper-tts/bin/python"   # usually ~/.local/share/uv/tools/piper-tts/bin/python

"$PIPER_PY" -m piper.download_voices                       # list voices
"$PIPER_PY" -m piper.download_voices \
    --download-dir ~/.local/share/piper en_US-lessac-medium  # download one
```

Without `--download-dir` it downloads into the current directory.

`uvx --from piper-tts python -m piper.download_voices ...` also works, but resolves
its own `piper-tts`, possibly a different version from the installed tool.

## Download directly

Voices live in the `rhasspy/piper-voices` Hugging Face repository, under
`<lang>/<lang_REGION>/<name>/<quality>/`:

```bash
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium
curl -fLO "$BASE/en_US-lessac-medium.onnx"
curl -fLO "$BASE/en_US-lessac-medium.onnx.json"
```

`-f` makes curl fail on a 404 instead of saving an HTML error page as the model.

## Default voice

To use a voice without `-m`, link both files under the default name:

```bash
cd ~/.local/share/piper
ln -s en_US-lessac-medium.onnx      default-voice.onnx
ln -s en_US-lessac-medium.onnx.json default-voice.onnx.json
```

## Check

```bash
uv run oddjob speak --text 'Hello from Piper.' -o hello.wav \
    -m ~/.local/share/piper/en_US-lessac-medium.onnx
```
