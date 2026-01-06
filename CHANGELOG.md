# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Structured Diagnostics**: Introduced `gm_diagnostics` tool (and `gms diagnostics` CLI command) providing machine-readable project diagnostics (JSON validity, naming conventions, structural orphans, and deep reference analysis). Issues include severity, category, diagnostic codes (e.g., `GM001`), and suggested fixes.
- **Runtime Management**: Implemented a comprehensive suite for GameMaker runtime version control:
    - `gm_runtime_list`: Discover all installed IDE/Runtime versions.
    - `gm_runtime_pin`: Lock a project to a specific runtime version via `.gms_mcp/runtime.json`.
    - `gm_runtime_unpin`: Revert to auto-selecting the newest stable runtime.
    - `gm_runtime_verify`: Comprehensive check of a specific runtime's validity (Igor, licenses, pathing).
- **Advanced Compilation Controls**: Updated `gm_compile` and `gm_run` to accept a `runtime_version` override, allowing for manual version testing without changing project-wide pins.
- **Structured Diagnostic Standard**: Implemented a standardized `Diagnostic` data format across the entire maintenance suite, enabling better integration with IDE problem panels and CI reporting.

### Fixed
- **CLI Import Regressions**: Resolved `ImportError` in `gms_helpers.commands` that occurred after previous refactoring, ensuring all asset and room commands are correctly exposed.
- **Runtime Discovery Pathing**: Fixed an issue where Igor pathing was hardcoded to older x86 paths; now dynamically resolves through the new `RuntimeManager`.

### Changed
- **Renamed Legacy Methods**: Standardized terminology across the codebase by removing mentions of third-party extensions in favor of generic terms like "IDE-temp approach".
- **Enhanced `gm_run`**: Improved the runner logic to better handle IDE-style temporary packaging and execution, including improved background process tracking.
- **Test Suite expansion**: Added `test_diagnostics.py` and `test_runtime_manager.py` to the core test suite, covering all new structured diagnostic and version management logic.
- **Documentation Refresh**: Fully updated `README.md` and `src/gms_mcp/README.md` to reflect the new diagnostics and runtime management capabilities.

## [0.1.1.dev41] - 2025-12-18 (Approximate)
### Added
- **Telemetry & Health Check**: Introduced `gm_mcp_health` tool (and `gms maintenance health` CLI command) for one-click diagnostic verification of the GameMaker development environment. It checks for project validity, Igor.exe, GameMaker runtimes, licenses, and Python dependencies.
- **Execution Policy Manager**: Created a central `PolicyManager` in `src/gms_mcp/execution_policy.py` that determines per-tool execution modes (`DIRECT` vs `SUBPROCESS`). This allows "Fast assets, Resilient runner" behavior, defaulting safe operations like introspection and asset creation to in-process execution while keeping long-running tasks like the runner in isolated subprocesses.
- **Typed Result Objects**: Introduced `@dataclass` result objects in `src/gms_helpers/results.py` (e.g., `AssetResult`, `MaintenanceResult`, `OperationResult`). This standardizes return values across tools, ensuring consistency and better integration with the MCP server.
- **Library-First Exception Hierarchy**: Introduced a comprehensive custom exception hierarchy (`GMSError` and subclasses) in `src/gms_helpers/exceptions.py`. This replaces monolithic `sys.exit()` calls in library code, allowing for structured error handling and clean JSON-RPC error codes in the MCP server.
- **Improved Error Reporting**: The MCP server now captures library-specific exceptions and returns descriptive error messages and exit codes, making it easier for users and agents to diagnose issues like missing `.yyp` files or invalid asset types.
- **Introspection Tools**: Implemented comprehensive project introspection tools including `gm_list_assets`, `gm_read_asset`, and `gm_search_references`. These tools support all GameMaker asset types, including **Extensions** and **Included Files (Datafiles)**.
- **Asset Dependency Graph**: Added `gm_get_asset_graph` tool with both **Shallow** (structural metadata only) and **Deep** (full GML code parsing) modes for tracing relationships between objects, sprites, scripts, and more.
- **MCP Resources**: Exposed addressable, cacheable project indices and graphs via MCP resources (`gms://project/index` and `gms://project/asset-graph`) for high-performance agent context loading.
- **Project Statistics**: Added `gm_get_project_stats` for quick summaries of project asset counts by type.
- **Project-Relative Debug Logging**: Debug logs are now normalized to `.gms_mcp/logs/debug.log` within the resolved project root, ensuring logs are captured correctly in both development and installed (`pipx`) environments.
- **Purge Command**: Implemented the previously stubbed `purge` command. It now correctly identifies orphaned assets, respects `maintenance_keep.txt` and `--keep` patterns, and safely moves files to a timestamped `.maintenance_trash` folder with an automatically generated `MANIFEST.txt`.
- **CI Test Suite**: Added a comprehensive CI test job to `publish.yml` that runs the full test suite and final verification across Linux and Windows on Python 3.11, 3.12, and 3.13, ensuring project stability before every build. Updated test runner to automatically create a minimal GameMaker project environment when running in clean CI environments.
- **Coverage Tooling**: Wired up `pytest-cov` and added coverage reporting targets in `pyproject.toml`. Developers can now generate HTML and terminal coverage reports using `pytest`.

### Fixed
- **MCP Resource Parameters**: Resolved a `ValueError` that prevented the MCP server from starting. Removed invalid `project_root` parameters from fixed URI resources (`gms://project/index` and `gms://project/asset-graph`), as FastMCP requires URI parameters to match function arguments.
- **Output Encoding**: Corrected a bug in `utils.py` where the UTF-8 fallback wrapper failed to reassign `sys.stdout` and `sys.stderr` on older Windows systems, ensuring Unicode-safe console output.
- **MCP Stdio Deadlocks**: Resolved "silent hangs" in Cursor by isolating subprocess stdin (`DEVNULL`) and disabling streaming logs (`ctx.log()`) during active execution.
- **Windows Performance**: Defaulted to in-process execution for MCP tools, making them near-instant on Windows and bypassing shim/wrapper overhead.
- **Asset Creation Defaults**: Assets created without an explicit `parent_path` now correctly default to the project root (mirroring GameMaker IDE behavior).
- **Invalid Room Schema**: Fixed invalid JSON generation for room `.yy` files by ensuring all 8 view slots include required fields (`hborder`, `objectId`, etc.).
- **FastMCP Parameter Conflict**: Renamed `constructor` parameter to `is_constructor` in `gm_create_script` to resolve internal naming conflicts in FastMCP.

### Changed
- **Execution Model Documentation**: Updated README and tool docstrings to align with the actual high-reliability subprocess execution model (standardizing on captured output and isolated stdin).
- **Project Root Resolution**: Standardized environment variable support across MCP server and CLI tools. Both now consistently check for `GM_PROJECT_ROOT` followed by `PROJECT_ROOT`, improving consistency when running in different environments.
- **Test Suite Logs**: Improved test output by clearly labeling expected errors during negative testing as `[EXPECTED ERROR]`, reducing confusion during CI runs.
- **Asset Creation Defaults**: MCP tools now default to `skip_maintenance=True` and `maintenance_verbose=False` for faster feedback loops.
- **Dedupe Resources**: `gm_maintenance_dedupe_resources` now defaults to `auto=True` to prevent interactive prompt hangs.
- **Legacy Removal**: Removed legacy `test_mcp_streaming_runner.py` in favor of the more stable direct/non-streaming architecture.
- **Test Suite Architecture**: CLI test suite now imports `gms_helpers` directly from `src` and uses module invocation, removing legacy shim modules.
