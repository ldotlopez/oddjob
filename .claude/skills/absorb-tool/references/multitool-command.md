# Porting a multitool command

1. **Domain**: `multitool/<area>.py`, no click, no I/O beyond the operation
   itself. Planning functions `plan_<op>(...)` return frozen dataclasses
   (`@dataclass(frozen=True, slots=True)`) with `describe()`; applying takes
   a plan item. See `conversions.py` (`Conversion`, `plan_conversions`,
   `run_conversion`), `motionphotos.py` (`Merge`, `plan_merges`),
   `renamers.py` (`Rename`, `plan_rename`, `apply_rename`).

2. **File types**: extend `multitool/media.py` when needed. It builds on
   `filejobs.inputs.media_type_filter`; only extensions that `mimetypes`
   gets wrong (like `EXTRA_VIDEO_EXTENSIONS`) or converter-specific sets
   belong there.

3. **External programs**: an adapter class in `multitool/external.py`:
   `_require_binary(...)` in `__init__` (missing → `FileNotFoundError`),
   `_run_tool([...])` for calls (failure → `RuntimeError`). ffmpeg goes
   through `filejobs.runners.FFMpegRunner`, never directly. Build adapters
   after the dry-run check, as `commands/conversions.convert_all` does with
   `build_step`, so `-n` works without the binary.

4. **Steps**: a `ProgressStep[Path]` class in the domain module taking its
   adapters in `__init__` (injected, so tests pass fakes), writing to
   `temp_output_path("multitool-<step>-", suffix)` and unlinking it on
   failure (`JpegConversionStep`, `Mp4RemuxStep`); or a `BytesStep` for
   in-memory transforms (motion photos).

5. **Command**: `multitool/commands/<area>.py`, one module per area; a click
   group when the area has subcommands (`motionphotos`). Use
   `filejobs.cli_options` (`paths_argument`, `overwrite_option`,
   `dry_run_option`, `run_jobs`, `run_single_job`, `finish_batch`).
   Register it in `COMMANDS` in `multitool/cli.py`. Logging comes from the
   group (`logging_options_for("multitool")`); do not add it per command.

6. **Optional dependencies**: after approval,
   `uv add --optional multitool <pkg>`. Import them only in the domain
   module that needs them; the command loads that module lazily with a clear
   "install the multitool extra (uv sync --extra multitool)" error, as
   `commands/imghash.load_imghash` does.

7. **Cache / user data**: `foundation.cache.UserCache(app="multitool")`,
   closed through `click.get_current_context().call_on_close`, as
   `commands/imghash.hash_cache` does. No ad-hoc paths.

Tests: `test_multitool_domain.py` (planning, pure logic),
`test_multitool_conversions.py`-style step tests against fake executables,
`test_multitool_commands.py` (`CliRunner`: `-n`, silent success with a
`wrote` log record, failure summary),
and `test_multitool_integration.py` classes that skip when a binary is
missing from PATH.
