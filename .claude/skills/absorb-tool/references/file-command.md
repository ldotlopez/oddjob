# Porting a file command

1. **Domain**: `oddjob/lib/<area>.py`, no click, no config or backends, no
   I/O beyond the operation itself. Planning functions `plan_<op>(...)`
   return frozen dataclasses (`@dataclass(frozen=True, slots=True)`) with
   `describe()`; applying takes a plan item. See `conversions.py`
   (`Conversion`, `plan_conversions`, `run_conversion`), `motionphotos.py`
   (`Merge`, `plan_merges`), `renamers.py` (`Rename`, `plan_rename`,
   `apply_rename`).

2. **File types**: extend `oddjob/lib/media.py` when needed. It builds on
   `filejobs.inputs.media_type_filter`; only extensions that `mimetypes`
   gets wrong (like `EXTRA_VIDEO_EXTENSIONS`) or converter-specific sets
   belong there.

3. **External programs**: an adapter class in `oddjob/lib/external.py`:
   `_require_binary(...)` in `__init__` (missing → `FileNotFoundError`),
   `_run_tool([...])` for calls (failure → `RuntimeError`). ffmpeg goes
   through `filejobs.runners.FFMpegRunner`, never directly. Build adapters
   after the dry-run check, as `commands/conversions.convert_all` does with
   `build_step`, so `-n` works without the binary.

4. **Steps**: a `ProgressStep[Path]` class in the domain module taking its
   adapters in `__init__` (injected, so tests pass fakes), writing to
   `temp_output_path("oddjob-<step>-", suffix)` and unlinking it on
   failure (`JpegConversionStep`, `Mp4RemuxStep`); or a `BytesStep` for
   in-memory transforms (motion photos).

5. **Command**: `oddjob/commands/<area>.py`, one module per area, objects
   named `<name>_cmd`; a click group when the area has subcommands
   (`motionphotos`). Use `filejobs.cli_options` (`paths_argument`,
   `overwrite_option`, `dry_run_option`, `run_jobs`, `run_single_job`,
   `finish_batch`). Every leaf command takes `@logging_options` (from
   `oddjob.core.cli_common`) right above its `def`, so `-v`/`-q`/
   `--log-level` follow the command name; no other option may use `-v` or
   `-q` (`test_file_commands.CommandTreeTests` checks it). Register it in
   `FILE_COMMANDS` and in a panel of `PANELS` in `oddjob/cli.py`. A plain
   command never takes `pass_session`; one that also needs a backend is a
   mixed command and follows `oddjob-task.md` for that part.

6. **Optional dependencies**: after approval,
   `uv add --optional images <pkg>` (or a new extra, if it is not an image
   library). Import them only in the domain module that needs them; the
   command loads that module lazily with a clear "install the images extra
   (uv sync --extra images)" error, as `commands/imghash.load_extra_module`
   does.

7. **Cache / user data**: `foundation.cache.UserCache(app="oddjob",
   base_dir=Path(platformdirs.user_cache_dir("oddjob")) / "<area>")`, closed
   through `click.get_current_context().call_on_close`, as
   `commands/imghash.hash_cache` does. No ad-hoc paths.

Tests: `test_file_domain.py` (planning, pure logic),
`test_conversions.py`-style step tests against fake executables,
`test_file_commands.py` (`CliRunner` on `oddjob.cli.cli`: `-n`, silent
success with a `wrote` log record, failure summary), and
`test_file_integration.py` classes that skip when a binary is missing from
PATH.
