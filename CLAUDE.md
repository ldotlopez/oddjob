# CLAUDE.md

Python conventions, architecture and `foundation` usage come from `~/.claude/rules/`
(`python.md`, `architecture.md`, `foundation.md`). oddjob-specific notes live in
`.claude/rules/oddjob.md`. This file holds only agent behavior for this repo.

## Behavior

- **Load confirmation:** Begin the first reply of every conversation with the exact word `Whatsup?`. Only in the first reply.
- **Refactor before implementing:** If a request violates SRP, KISS or DRY, rewrite the approach before coding, then state briefly what you changed and why.
- **Edit over create:** Prefer editing existing files to creating new ones.
- **No half-baked code:** No `TODO` comments, placeholder logic or mock returns in completed code.
- **Dependencies:** When adding an approved package, run `uv add <package>` in the same step.
- **Style:** Concise and direct, no filler, without becoming terse or abrupt.
- **Honest evaluation, no edits:** When asked for an evaluation, opinion, review or critique, give a candid assessment with concrete reasons, and say plainly if an idea is bad. In this mode write no code and touch no files; act only after an explicit request.

## Search scope

- Never run unbounded recursive searches (`grep -r`, `find .`, `ls -R`, `**/*`). Always name a subdirectory and extension (e.g. `oddjob/`, `*.py`).
- If a repo-wide search is truly necessary, stop and ask first, stating why and the pattern you will use.
- If two targeted searches find nothing, stop and ask for the location instead of widening the search.

## `foundation`

- Its source path differs per developer. Locate it with:
  `uv run python -c "import foundation, pathlib; print(pathlib.Path(foundation.__file__).parent)"`
  and read the source there instead of guessing signatures or error types.
- Use only names exported in each module's `__all__`; never import `_`-prefixed modules or names.
- Never modify `foundation` from this repo; propose the change separately.

## Documentation

- Read `README.md`, `docs/ARCHITECTURE.md` and `docs/decisions/` when they exist: README at task start, ARCHITECTURE before adding modules or moving layer boundaries, decisions before changing an established approach. Do not reverse a recorded decision without asking.
- Never edit these files without explicit permission. After a change that makes one inaccurate (module added/renamed/re-scoped, CLI flag or behavior changed, roadmap item done, architectural decision made), list the affected files with a one- or two-line summary of the edit each, and wait for a yes. Once approved, change only what became inaccurate.
- `docs/decisions/` is append-only: to reverse a decision, add a superseding record and change only the old record's status line to `superseded by NNNN`.
- If unsure whether a doc update is warranted, ask.
