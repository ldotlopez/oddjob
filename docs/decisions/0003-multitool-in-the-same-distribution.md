# 0003. multitool lives in the glados distribution, without the plugin system

Status: superseded by 0011

## Context

The file utilities of ocdutils (`ocdutils/u/tools`: sidecars, motion photos,
format conversion, image hashing and duplicates, hash renaming) are to become a
second command-line tool, `multitool`. They need much of what glados already
has for file tasks (progress reporting, the `Job` temp-file → destination
flow, destination policies, the ffmpeg runner, logging and file options, and
the multiple-input expansion specified in `ARCHITECTURE.md`, "Inputs"), but
none of them has interchangeable implementations, so the backend registry
(0001, 0002) does not apply to them.

## Decision

- multitool is a second top-level package, `multitool/`, in this repository
  and in the same distribution (one `pyproject.toml`), installed through its
  own `[project.scripts]` entry point, `multitool`.
- glados' code splits into a backend-free part and a backend part. multitool
  imports only the backend-free part:
  - may import: `core/pipeline.py`, `core/progress.py`, `core/runners.py`,
    the input expansion, and the generic click options (file options,
    logging options);
  - must not import: `core/backends.py`, `core/config.py`,
    `core/text_backend.py`, `GladosContext`, `glados.plugins`, `glados.tasks`.
  `core/cli_common.py` currently holds both kinds and has to be split first.
- glados never imports `multitool`.
- multitool's third-party dependencies go in an optional extra (`multitool`),
  so installing glados alone does not pull them in. Each one still needs
  approval under the dependency policy.
- multitool has no backends, entry-point groups or `[backends.*]` config.

## Scope

- Ported from ocdutils: `sidecars` (`scan`, `find`), `motionphotos` (`check`,
  `join`, `split`, `strip`, `merge`), `jpgize`, `mp4ize`, `img-hash`,
  `img-duplicates`, and `renamers` as `hash-rename`. The other names stay as
  in ocdutils. `audio transcribe` is not ported: `glados transcribe` replaces
  it.
- Dependencies of the `multitool` extra: Pillow and pillow-heif only. The
  average hash is implemented in multitool (no `imagehash`, so no
  numpy/scipy), and file types come from stdlib `mimetypes` (no
  `python-magic`). ImageMagick and `exiftool` stay as runtime binaries;
  ffmpeg goes through `core/runners.py`.
- `img-duplicates` compares hashes by Hamming distance (`--max-distance`,
  small default) and reports connected components of near pairs as groups,
  instead of ocdutils' exact hash equality.
- Commands that change files (`jpgize`, `mp4ize`, `motionphotos`,
  `hash-rename`) plan first and then apply, and take `--dry-run`.

## Consequences

- One repository, one lockfile, no publishing step between the shared code
  and its two users; the cheapest structure to start with.
- The boundary is held by convention only: both packages are importable in
  the same environment, so a forbidden import does not fail by itself. Review
  must catch it.
- Changing the backend-free part of `core/` can break multitool; both tools'
  tests run together.
- `ARCHITECTURE.md`, the README and the pyproject description must describe
  two tools once multitool exists.

## Alternatives, and how to switch

- **uv workspace with three members** (shared core, glados, multitool, each
  with its own `pyproject.toml` under `packages/`, one `uv.lock`): separate
  dependencies, and the boundary becomes checkable by running multitool's
  tests in an environment synced with `uv sync --package multitool`. Costs a
  repository restructure and a real `[build-system]` per member. Switch to it
  if the convention above is broken in practice, or if one tool's
  dependencies become a burden for the other: move the backend-free modules
  into the shared member, `glados/` and `multitool/` into their own members,
  and declare the shared one with `{ workspace = true }` in each.
- **Separate repository, depending on glados**: independent releases, but
  glados' backend-free core becomes a public API that has to stay stable.
  Switch to it only if multitool needs its own release cycle; prefer the
  workspace first.
- **Shared code in `foundation`**: right only when a project outside this
  repository needs it. Move the backend-free modules there then, and import
  them from both tools.
