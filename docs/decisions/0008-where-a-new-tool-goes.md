# 0008. Where a new tool goes: not absorbed, glados, multitool or filejobs

Status: accepted (2026-11-06). Extends 0003's scope.

## Context

0003 created multitool and listed which ocdutils tools it would take, by
name. It gave no rule for the next tool. More tools keep arriving (scripts,
ocdutils leftovers, one-off utilities), and each one raised the same
questions: does it belong in glados or multitool, should it be absorbed at
all, and what happens to a tool that is half model and half file
operation. Answered per tool, the answers drift: in ocdutils `mediatools/`,
duplicate finding, a deterministic file operation, chose between
averagehash and cv2histogram through the same backend factory as the model
tasks.

The first round under the `absorb-tool` skill (`docs/plans/absorbing-tools.md`,
ocdutils `mediatools/`) applied the rules below to eleven candidates. Six
were ported, one was left out by the user, and the rest were not absorbed.

## Decision

A tool is classified by the first rule that matches.

1. **Not absorbed** if it is interactive, a long-running service, or
   machine- or account-specific. A library needed outside this repository
   goes to `foundation` instead, as a separate proposal; it is never edited
   from here.
2. **glados task** if its core operation goes through a model, a remote
   service, or a CLI that has alternatives. This holds even when only one
   backend exists today, as long as a second is plausible. The task gets a
   Protocol, backends in `glados/plugins/`, and config.
3. **multitool command** if it is a deterministic file operation with one
   implementation. The external programs it runs (ImageMagick, exiftool,
   ffmpeg) are adapters, not backends.
4. **filejobs** receives a generic piece only once both tools need it (a
   second consumer). filejobs never imports `glados` or `multitool`.

A tool must also fit one of 0004's command shapes (file producer, single
file, report/rename/check), each taking `PATH...`. One that fits none,
such as a generator with a prompt and no input files, or a persistent
index, is not absorbed until a new shape is decided in its own record.

**Mixed tools** (a model part and a file part) are split along the model
boundary. The glados task writes a sidecar, a multitool command consumes
sidecars, and the user composes the two in the shell. If the split is
unnatural, the whole tool is a glados task. Any multitool code it needs then
moves to filejobs if it is generic, or is rewritten in the task. multitool
code is never copied into glados, a backend is never resolved from
multitool, and glados never imports multitool.

**Naming**: command names are unique across both tools. glados tasks are
also standalone scripts, so their names must not clash with common system
commands; multitool commands get no standalone script. A tool keeps its
source name unless the name clashes or misdescribes it (`renamers` became
`hash-rename`, `photos-check` became `img-check`, and `agrep` became
`srt-grep`).

## Applied in the first round

- glados: `translate` (text backends). `describe-image` split into
  `glados describe` (writes `NAME.description.txt`) and
  `multitool img-caption` (writes it into the image's metadata).
- multitool: `fix-extensions`, `img-check`, `autocrop`. `agrep` split into
  `glados transcribe -f srt` (already present) and `multitool srt-grep`.
- Not absorbed: `create-image` (no `PATH...` shape), `emojize`
  (`rewrite -i` covers it), `embeddings` (an index fits no shape),
  `cv2histogram` (0003 chose the average hash for `img-duplicates`).
  `removebg` would have been a glados task, but the user left it out.

## Consequences

- Classification is mechanical and gives the same answer for the same tool.
  `docs/plans/absorbing-tools.md` records each tool's result in its
  inventory.
- A model-backed tool always gets a backend boundary, even with a single
  backend, so a second backend is just a plugin. The cost is a Protocol and
  entry points that look like ceremony while only one backend exists.
- Splitting mixed tools keeps both import boundaries
  (`tests/test_boundaries.py`) without exceptions. Users then run two
  commands instead of one.
- Tools that fit no command shape stay out until a record adds a shape,
  rather than each one inventing its own.

## Alternatives

- **Decide per tool in its own record:** precise, but one record per tool
  and no shared answer to "where does this go".
- **Classify by dependencies** (anything needing a network or model library
  goes to glados): simpler, but it misplaces deterministic tools that call a
  heavy library (Pillow) and model tools that only shell out to a CLI
  (`llm`).
- **Everything in glados, with single-backend tasks for file utilities:**
  one tool and one layout, but backends and config for operations that will
  never have a second implementation, which is what 0003 set out to avoid.
- **Never split mixed tools** (each is one glados task): one command per
  tool, but the file half becomes unreachable without a model, and glados
  ends up duplicating multitool's file code.
