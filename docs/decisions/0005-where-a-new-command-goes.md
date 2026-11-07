# 0005. Where a new command goes

Status: accepted (2026-11-07)

## Context

New tools keep arriving: scripts, ocdutils leftovers, one-off utilities.
Each raises the same questions: should it be absorbed at all, does it need
backends, and what happens to a tool that is half model and half file
operation. Answered per tool, the answers drift. The `absorb-tool` and
`create-tool` skills apply the rules below.

## Decision

A tool is classified by the first rule that matches.

1. **Not absorbed** if it is interactive, a long-running service, or
   machine- or account-specific. A library needed outside this repository
   goes to `foundation` instead, as a separate proposal; it is never edited
   from here.
2. **Task** if its core operation goes through a model, a remote service, or
   a CLI that has alternatives, even when only one backend exists today, as
   long as a second is plausible. It gets a Protocol (`lib/protocols.py`),
   backends in `oddjob/plugins/`, an entry-point group (0001) and config
   (0002). A command may reuse another task's backends without a group of its
   own (`audio-grep` uses `transcribe`'s).
3. **Plain command** otherwise. The external programs it runs (ImageMagick,
   exiftool, ffmpeg) are adapters in `oddjob/lib/`, not backends.
4. **`filejobs`** receives a generic piece only once a second command needs
   it.

A tool with a model part and a file part is one command, resolving the
backend through `pass_session` (0003).

A tool must also fit one of the command shapes of 0004 (file producer,
single file, report/rename/check), each taking `PATH...`. One that fits
none, such as a generator with a prompt and no input files, or a persistent
index, is not absorbed until a new shape is decided in its own record.

**Naming**: command names are unique. A tool keeps its source name unless the
name clashes or misdescribes what the command does.

**Not absorbed so far**, so not to be proposed again without a new reason:

| Tool | Reason |
|---|---|
| `create-image` | a prompt, no `PATH...`: no command shape |
| `emojize` | `rewrite -i` covers it |
| `embeddings` | a persistent index: no command shape |
| `cv2histogram`, `mdupes` | `img-duplicates` compares average hashes by Hamming distance, implemented here, with no opencv, numpy or imagehash |
| `removebg` | left out by the user; would be a task needing `rembg` (onnxruntime) |
| `sidecars` video prune | `motionphotos merge --rm` (after `jpgize`/`mp4ize`) does it without losing the video |
| `checksumrenamer`, `metadata` | unfinished; `rename-by-hash`, `exiftool` and `stat` cover them |
| `filesystem`, `ocdlib` | library code that `filejobs` and `lib/renamers.py` replace |

File types come from stdlib `mimetypes`, not `python-magic`.

## Consequences

- Classification is mechanical and gives the same answer for the same tool.
- A model-backed tool always gets a backend boundary, even with a single
  backend, so a second backend is just a plugin. The cost is a Protocol and
  entry points that look like ceremony while only one backend exists.
- Tools that fit no command shape stay out until a record adds a shape,
  rather than each inventing its own.

## Alternatives

- **Decide per tool in its own record**: precise, but no shared answer to
  "where does this go".
- **Classify by dependencies** (anything needing a network or model library
  is a task): misplaces deterministic tools that call a heavy library
  (Pillow) and model tools that only shell out to a CLI (`llm`).
- **Every command a task, file utilities with a single backend**: one shape,
  but backends and config for operations that will never have a second
  implementation.
- **Split mixed tools along the model boundary** (a task writes a sidecar, a
  plain command reads it, the shell composes them): tried and dropped; it
  took two commands for one job and left sidecars nobody asked for.
