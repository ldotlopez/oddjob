# 0008. The name: oddjob

Status: accepted (2026-11-07)

## Context

The project started as `glados`, a tool to run files through language and
speech models. It now also holds file utilities (sidecars, motion photos,
conversions, image hashes, renames, date sync, cleanup), more than half of
its commands. The name suggested an AI tool only.

## Decision

- The project is `oddjob`: a handyman for odd jobs on files. The name is
  used wherever it acts as a namespace: distribution, package and script,
  entry-point groups (`oddjob.backends.<task>`), the plugin hook
  (`__oddjob_plugin__`), environment variables (`ODDJOB_*`), the logger, the
  config and cache directories, and temp-file prefixes.
- Classes and functions are named for what they are, not after the product:
  the run's session object is `Session` (`pass_session`).
- No fallback to the old name: `$XDG_CONFIG_HOME/glados`,
  `$XDG_CACHE_HOME/glados` and `GLADOS_*` are not read.

## Consequences

- Breaking for the current user: run `oddjob`, move `config.toml` to
  `$XDG_CONFIG_HOME/oddjob/`, rename `GLADOS_*` variables (including
  `tests/integration.env`), and delete the old cache directory; cached
  values are recomputed once.
- A future rename touches only namespaces, not class or function names.

## Alternatives

- **Keep `glados`** as an opaque brand: no churn, but it keeps suggesting an
  AI-only tool.
- **`multitool`**: generic, long to type, and the name of the file-utilities
  half before the tools merged, which makes the history read backwards.
- **Other names**: `navaja`, `tinker`, `fettle` and others were weighed;
  `oddjob` is short, free on PyPI and says what the tool is.
- **Read the old config path and variables as a fallback**: no user outside
  the author, so not worth a second code path.
