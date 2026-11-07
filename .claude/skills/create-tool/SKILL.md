---
name: create-tool
description: Design and build a brand-new glados command from an idea or a need, with no existing script to port: a task (model/service-backed, replaceable backends), a plain file command, or a mixed one. Settles the spec with the user, checks no existing command already does it, picks name, panel and shape, writes tests from the spec, then builds it to the repository's conventions. Use whenever the user wants to create, write, add, design or "make" a new tool, command, subcommand, task or backend-backed command for glados, or asks "can glados do X" for something it cannot do yet, even if they do not name this skill. For porting an existing script or ocdutils leftover, use absorb-tool instead.
---

# Create a new glados tool

A new tool follows the same conventions as an absorbed one; only the
starting point differs. With no source to read, the behavior comes from
the user, so the work is: settle a spec, turn it into tests, then build.

The conventions themselves live in the `absorb-tool` skill and are not
repeated here. Read them before starting:

- `.claude/skills/absorb-tool/SKILL.md`: the repository layout (intro),
  **2. Classify**, **3. Pick the command shape**, **5. Test**,
  **6. Checklist** and **7. Propose documentation**.
- `.claude/skills/absorb-tool/references/file-command.md` and
  `references/glados-task.md`: how to build each kind.

Also read `README.md`, `docs/ARCHITECTURE.md` and `docs/decisions/`
(project rule), and `.claude/rules/glados.md` for the current command list.

One tool per commit. Write no code before step 4 is approved.

## 1. Check it does not exist yet

Look up the commands in `.claude/rules/glados.md` and `PANELS` in
`glados/cli.py`. If one already covers most of the need, an option or a
subcommand on it is usually better than a new command (edit over create):
propose that to the user and stop here unless they want a separate command.

## 2. Settle the spec, one question at a time

Use the `one-question-at-a-time` skill. Infer what the repository already
answers; ask only what is the user's call, most foundational first, since
early answers remove later questions:

1. **What it does**, as one example invocation and its effect
   (`uv run glados <name> ~/Pictures` → ...).
2. **Effect on files**: new file per input, rewrite in place, rename/move,
   or only a report. This picks the shape (absorb-tool, step 3).
3. **Model, service or CLI with alternatives?** This picks the
   classification (absorb-tool, step 2): task, plain file command or mixed.
   A plausible second implementation is enough to make it a task.
4. **Inputs**: which file types (the `expand_inputs` filter), directories
   recursed as usual.
5. **Options** beyond the shared ones (`-n`, `-y`, `-o`, logging): each
   with its default. Per-run values are method arguments; backend settings
   are options of the backend's model.
6. **Runtime needs**: external binaries on PATH, services, new Python
   packages. A package outside the dependency policy needs explicit
   approval before anything else; Pillow-based code goes under the
   `images` extra.
7. **Edge behavior** only where the conventions leave a real choice (what
   counts as "nothing to do", what a failed input means). Everything the
   conventions decide (exit codes, silence on success, `-y` up front,
   `-n` plans) is not a question.

## 3. Name and place

Propose these with the spec; ask only if there is a genuine alternative.

- **Name**: lowercase, hyphenated, unique. Match the existing families:
  `img-<verb>` for image operations (`img-reduce`, `img-check`),
  `<format>ize` for conversions to a format (`jpgize`, `mp4ize`),
  `<noun>-<verb>` for file operations (`hash-rename`, `date-sync`,
  `fs-cleanup`), a bare verb for tasks (`summarize`, `translate`). Several
  operations on one subject become a group with subcommands
  (`motionphotos`, `sidecars`).
- **Module**: `glados/commands/<area>.py` (an existing area module if the
  tool belongs to it), object `<name>_cmd` with hyphens as underscores;
  domain code in `glados/lib/<area>.py`.
- **Panel**: one of `PANELS` in `glados/cli.py` (Text, Audio, Images,
  Media, Files). A new panel needs the user's yes.

## 4. Confirm the spec

Write it back as one compact block and wait for an explicit yes:

```
name / panel:     img-rotate / Images
classification:   plain file command (shape: file producer)
inputs:           images (media.is_image)
effect:           NAME.rotated.<ext> (infix_destination); -y to replace it
options:          --angle {90,180,270} (default 90)
-n prints:        rotate 90 a.jpg -> a.rotated.jpg
fails when:       not decodable → that input fails, the rest continue
runtime / deps:   Pillow (images extra), no binary
```

## 5. Tests first

The spec is the only reference behavior, so turn its lines into tests
before the implementation (absorb-tool, step 5, says which kinds):

- the example invocation and `-n` output → CLI tests with `CliRunner`;
- each option and failure line → a CLI or domain test;
- planning and pure logic → domain tests; adapters → fake executables or
  `support.FakeHTTPServer`.

Run them and see them fail for the right reason (the command does not
exist yet, not an import or fixture error).

## 6. Build

Follow absorb-tool step 4 ("Port") with this tool as the source: the
reference for its kind, and the closest existing command read first and
matched. Register it in `FILE_COMMANDS` or `TASK_COMMANDS` and its panel;
a task also gets its entry-point group in `pyproject.toml` and `uv sync`.

## 7. Verify and report

- absorb-tool's step 6 checklist, without the inventory row (a new tool has
  none in `docs/plans/absorbing-tools.md`).
- ruff and the full test suite green.
- Run it once for real on a scratch directory: `uv run glados <name>
  --help`, then `-n`, then the real run, and check stdout is only what the
  spec says.
- Propose documentation as in absorb-tool step 7 (README, ARCHITECTURE,
  `.claude/rules/glados.md`, `pyproject.toml` description, a decision
  record only if the tool changes an approach). Edit nothing until the user
  says yes.
