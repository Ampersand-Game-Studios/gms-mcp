# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Purge Command**: Implemented the previously stubbed `purge` command. It now correctly identifies orphaned assets, respects `maintenance_keep.txt` and `--keep` patterns, and safely moves files to a timestamped `.maintenance_trash` folder with an automatically generated `MANIFEST.txt`.
- **CI Test Suite**: Added a comprehensive CI test job to `publish.yml` that runs the full test suite and final verification across Linux and Windows on Python 3.11, 3.12, and 3.13, ensuring project stability before every build. Updated test runner to automatically create a minimal GameMaker project environment when running in clean CI environments.
- **Coverage Tooling**: Wired up `pytest-cov` and added coverage reporting targets in `pyproject.toml`. Developers can now generate HTML and terminal coverage reports using `pytest`.

### Fixed
- **Output Encoding**: Corrected a bug in `utils.py` where the UTF-8 fallback wrapper failed to reassign `sys.stdout` and `sys.stderr` on older Windows systems, ensuring Unicode-safe console output.
- **MCP Stdio Deadlocks**: Resolved "silent hangs" in Cursor by isolating subprocess stdin (`DEVNULL`) and disabling streaming logs (`ctx.log()`) during active execution.
- **Windows Performance**: Defaulted to in-process execution for MCP tools, making them near-instant on Windows and bypassing shim/wrapper overhead.
- **Asset Creation Defaults**: Assets created without an explicit `parent_path` now correctly default to the project root (mirroring GameMaker IDE behavior).
- **Invalid Room Schema**: Fixed invalid JSON generation for room `.yy` files by ensuring all 8 view slots include required fields (`hborder`, `objectId`, etc.).
- **FastMCP Parameter Conflict**: Renamed `constructor` parameter to `is_constructor` in `gm_create_script` to resolve internal naming conflicts in FastMCP.

### Changed
- **Project Root Resolution**: Standardized environment variable support across MCP server and CLI tools. Both now consistently check for `GM_PROJECT_ROOT` followed by `PROJECT_ROOT`, improving consistency when running in different environments.
- **Test Suite Logs**: Improved test output by clearly labeling expected errors during negative testing as `[EXPECTED ERROR]`, reducing confusion during CI runs.
- MCP tools now default to `skip_maintenance=True` and `maintenance_verbose=False` for faster feedback loops.
- `gm_maintenance_dedupe_resources` now defaults to `auto=True` to prevent interactive prompt hangs.
- Removed legacy `test_mcp_streaming_runner.py` in favor of the more stable direct/non-streaming architecture.
- CLI test suite now imports `gms_helpers` directly from `src` and uses module invocation, removing legacy shim modules.
