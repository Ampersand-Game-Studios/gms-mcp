# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **GML Documentation Lookup**: Built-in documentation for GameMaker functions fetched on-demand from manual.gamemaker.io:
    - `gms doc lookup <function>`: Look up specific GML function documentation (description, syntax, parameters, return value, examples)
    - `gms doc search <query>`: Search for GML functions by name
    - `gms doc list`: List functions by category or regex pattern
    - `gms doc categories`: Show all documentation categories
    - `gms doc cache stats/clear`: Manage local documentation cache
    - MCP tools: `gm_doc_lookup`, `gm_doc_search`, `gm_doc_list`, `gm_doc_categories`, `gm_doc_cache_stats`, `gm_doc_cache_clear`
    - Indexes 1000+ GML functions with TTL-based caching (30 days for functions, 7 days for index)
- **Claude Code Plugin**: Restructured as a Claude Code plugin with skills, hooks, and auto-configured MCP:
    - Install via `/install-plugin github:Ampersand-Game-Studios/gms-mcp`
    - Session-start hook checks for updates and bridge status
    - Error notification hook surfaces compile failures
    - Skills moved to plugin directory (pip package unchanged for other tools)
- **Claude Code Skills**: Introduced a comprehensive skills system for Claude Code with 18 workflow guides and 7 reference documents:
    - `gms skills install`: Install skills to user or project directory.
    - `gms skills list`: List available skills and installation status.
    - `gms skills uninstall`: Remove installed skills.
    - Workflows include: asset creation, event management, refactoring, project maintenance, game running/debugging, and code intelligence.
    - Reference docs cover: asset types, event types, room/layer commands, maintenance operations, runtime options, and symbol commands.
- **GML Symbol Indexing & Code Intelligence**: Implemented a core GML parsing and indexing engine for advanced code analysis:
    - `gm_build_index`: Scan the entire project and build a high-performance cache of symbols (functions, enums, macros, globalvars, constructors) and their references.
    - `gm_find_definition`: Instantly jump to the definition of any GML symbol.
    - `gm_find_references`: Trace all usages of a symbol across the project.
    - `gm_list_symbols`: Filtered listing of all project symbols by type, name, or file.
- **Improved MCP Logging**: Updated the MCP server to suppress informational SDK logs that were previously sent to `stderr`, preventing Cursor from incorrectly flagging them as `[error]` markers.
- **Enhanced Asset Compatibility**: Standardized object (`.yy`) and event (`.gml`) generation formats to ensure 100% compatibility with GameMaker's **Igor** compiler (fixing "No version changes" and JSON schema errors).
- **macOS Reliability Improvements**:
  - Added Apple Silicon runtime discovery for `bin/igor/osx/arm64/Igor`.
  - Added session-safe game process launch and cleanup so macOS child processes are properly tracked/terminated.
  - Improved GameMaker license discovery for newer and legacy filename spellings (`license.plist` and `licence.plist`) with recursive fallbacks.
  - Normalized path comparison behavior to avoid case-related mismatches on macOS case-insensitive volumes.

### Fixed
- **Spurious `.gms_mcp` Folder Creation**: Fixed an issue where the MCP server would create a `.gms_mcp/logs/` folder in the current working directory even when no GameMaker project was present. Debug logging now only activates when a valid project is detected.
- **Object Creation Schema**: Fixed a critical bug where newly created objects were missing required `$GMObject: "v1"` markers, which prevented project compilation.
- **Event Creation Schema**: Updated the event management system to use `resourceVersion: "2.0"` and required `%Name` fields, ensuring modern GameMaker compatibility.
- **CLI Subcommand Registration**: Resolved an issue where `symbol` commands were not correctly registered in the main `gms` CLI entry point.
- **Test Suite assertions**: Updated 371-test suite to reflect the new standardized asset versioning requirements.

### Changed
- **Diagnostic output**: Refined tool outputs to be cleaner and more consistent across the code intelligence suite.
- **Standardized Versioning**: Locked default asset creation to GameMaker 2024.x+ standards.

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
