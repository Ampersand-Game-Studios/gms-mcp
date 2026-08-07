# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Security
- **Public Artifact Boundary**: Removed repository-only project, planning, service-operation, and release material from the public tree; package builds now use an explicit runtime allowlist and fail CI or publication if generated archives contain development files, personal author contact metadata, or SCM repository inventories.
- **GitHub Actions Hardening**: Restricted workflow tokens and third-party actions, removed self-hosted runner access, and confined licensed GameMaker smoke jobs to a branch-restricted environment with a non-publishing manual verification path.
- **Privacy-Safe Local Diagnostics**: Codex previews now omit unrelated configuration and redact secret values and host paths. Automatic diagnostic logs now use private, opaque per-project directories under `~/.gms-mcp/logs/` instead of writing inside GameMaker projects.

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
  - Added a dedicated mockless macOS smoke test for real `.app` bundle launch path resolution.
  - Added macOS-specific launch/runtime permission diagnostics for sandbox blocks and unsigned binaries, including actionable remediation guidance.
- **Coverage Audit Expansion**: Added focused coverage suites for CLI wrappers, helper-heavy modules, install/setup flows, bridge tools, and reporting regressions. Release artifacts now enforce 85% overall and 50% per-module statement coverage gates.
- **LTS2026 Runtime Awareness**: Runtime discovery now classifies `2026.*` installs as LTS, and runner runtime labels accept the LTS2026 UI aliases `GMS2 VM` and `GMS2 YYC`.
- **LTS2026 Asset Introspection Coverage**: Added regression coverage for particle-system assets and lower-case project-serializer key variants.
- **GameMaker Verification Smoke**: Added `scripts/run_real_gamemaker_smoke.py` to copy a neutral fixture, exercise smart post-mutation verification, compile a high-risk mutation, defer a batchable sprite-frame mutation, and flush the pending compile once. CI runs a fixture matrix for 2024 and 2026/LTS when configured.
- **CI MCP Tool Smoke Coverage**: CI now runs a deterministic MCP tool smoke subset against a generated minimal GameMaker project fixture and publishes `mcp_tool_smoke_report.json` with quality artifacts.
- **Curated MCP Profiles**: The default server now exposes a focused 29-tool core. Optional domains are enabled with `GMS_MCP_TOOLSETS`, and `gm_capabilities` reports the active profile.
- **Release Certification**: Publication now consumes immutable artifacts from the exact successful CI commit and requires passing GameMaker 2024 and 2026 LTS compile fixtures, including collision-event serialization.
- **Mutation Journal**: Project writes now use cross-thread/process locking, selective journal rollback, ownership conflict detection, and cancellation-safe cleanup.

### Fixed
- **macOS Orphan Download Runner Cleanup**: Runner launches now wait briefly for IDE- or MCP-originated Igor activity to finish, reject a concurrent post-check Igor, snapshot every existing `Mac_Runner`, and attach a per-launch marker inherited through LaunchServices. Failure, timeout, validation, foreground-exit, and stop cleanup can terminate exact owned path-bearing or bare Download runners and log tails without killing pre-existing, concurrent user, or unrelated GameMaker processes; parent-side cleanup also catches worker-detached helpers.
- **Licensed CI Project Boundary**: Real GameMaker certification now pins the MCP server to its generated fixture before startup, so repository toolchain symlinks cannot be mistaken for unsafe links inside the GameMaker project.
- **Project-Confined MCP Access**: MCP servers now pin one GameMaker project at startup, reject traversal and symlink escapes for reads and writes, emit project-relative paths, and withhold host commands, process IDs, runtime/licence locations, and other machine diagnostics unless a trusted local server explicitly opts in.
- **Spurious `.gms_mcp` Folder Creation**: Fixed an issue where the MCP server would create a `.gms_mcp/logs/` folder in the current working directory even when no GameMaker project was present. Debug logging now only activates when a valid project is detected.
- **Object Creation Schema**: Fixed a critical bug where newly created objects were missing required `$GMObject: "v1"` markers, which prevented project compilation.
- **Event Creation Schema**: Updated the event management system to use `resourceVersion: "2.0"` and required `%Name` fields, ensuring modern GameMaker compatibility.
- **CLI Subcommand Registration**: Resolved an issue where `symbol` commands were not correctly registered in the main `gms` CLI entry point.
- **Test Suite Assertions**: Updated the full suite to reflect standardized asset versioning requirements.
- **Run Session process termination on Windows**: Fixed `RunSessionManager.kill_process` to use fallback signal values when platform `signal` constants are unavailable, preventing Windows-only failures in process teardown and ensuring CI reliability across `test_run_session`.
- **macOS Local Compile/Run Pipeline**: Fixed `gm_compile` and default local `gm_run` behavior on macOS so local validation uses Igor's run-based path instead of `PackageZip`, avoiding incorrect Developer ID signing/certificate failures during normal IDE-equivalent compile/run workflows. macOS background run sessions now track and stop the real `Mac_Runner` process cleanly.
- **GMRT Runner Requests**: `GMRT` and `GMRT VM` runtime labels are now recognized and rejected with an explicit unsupported message instead of being passed through as ambiguous Igor commands.
- **macOS Runner Smoke Reliability**: The mockless `.app` launch smoke now verifies that the executable actually runs and cleans up the child process instead of assuming a detached game process exits immediately.
- **LTS2026 Igor Stability**: Igor subprocesses now use bounded .NET processor concurrency by default, and confirmed pre-compile runtime abort retries clear only the affected project/runtime cache before trying again.
- **Portable Codex Configuration**: Workspace `.codex/mcp.toml` files now store project-relative `GM_PROJECT_ROOT` values and reject roots outside the workspace, preventing usernames and machine-specific paths from being committed. Global Codex registration omits the project root entirely.
- **Privacy-Safe Release Evidence**: Real GameMaker certification artifacts now publish only fixture filenames, hashes, IDE versions, runtime versions, and semantic checks; runner-local source, runtime, and work paths are omitted.

### Changed
- **MCP Tool Surface**: Named, annotated tools are the only MCP execution surface. Destructive policy is derived from full command prefixes and `gm_safe_delete` is the sole general asset-deletion endpoint.
- **Diagnostic output**: Refined tool outputs to be cleaner and more consistent across the code intelligence suite.
- **Legacy Helper Results**: Command/MCP paths that still call print-heavy legacy helpers now normalize raw booleans, ad-hoc error dictionaries, list payloads, and direct safe-delete workflow results into structured `success`/`ok`/`message`/`error` result payloads with operation data under `data`.
- **MCP Write Validation**: MCP mutation tools now validate typed operation models before transactions, direct helper calls, or CLI subprocess fallback. Domain validation failures stop at the MCP boundary instead of retrying through a generic fallback path, and real destructive MCP writes no longer accept `prefer_cli` or infrastructure fallback to the broad CLI path.
- **Standardized Versioning**: Locked default asset creation to GameMaker 2024.x+ standards.
- **Quality Reporting Pipeline**: `scripts/generate_quality_reports.py` now collects subprocess coverage correctly, combines parallel `.coverage*` data before writing `coverage.xml`, and keeps the published markdown/XML/JSON quality artifacts aligned with real CLI execution paths.
- **Smart Mutation Verification Default**: Post-mutation verification now defaults to smart mode, compiling high-risk structural mutations immediately while deferring batchable edits until `gm_verification_flush`.
- **Coverage Gates**: Quality reports now fail below 85% overall statement coverage or 50% per-module statement coverage by default, with gate details recorded in `quality_summary.json`.
- **Post-Mutation Compile Semantics**: Compile verification now treats a completed Igor compiler stage as a valid post-mutation compiler check even when a later local runner/package step exits non-zero for environment reasons.
- **GameMaker Runtime Selection**: Unpinned projects prefer a runtime matching their recorded IDE family, then the newest stable runtime. Confirmed pre-compile LTS `AccessViolationException` aborts receive a bounded retry; compiler failures and post-compile exits do not.
- **Asset Parent Defaults**: Omitted asset parents now resolve to the project's logical asset-type folders instead of placing new resources at project root.
- **Token-Aware Workflows**: Rename, duplicate, and safe-delete use token-aware GML and structured resource updates without broad maintenance side effects; rename blocks ambiguous GML bindings before mutation.
- **Bounded Diagnostics**: Direct output, subprocess logs, and debug logs are bounded; sensitive command values are redacted and child process trees are terminated on timeout or cancellation.

### Removed
- **Redundant MCP Entry Points**: Removed `gm_cli`, `gm_asset_delete`, and `gm_workflow_delete` along with their duplicated policy paths.
- **Unused Dependencies**: Removed the unused `fastmcp` and `tqdm` dependency surface and the duplicate requirements file; `uv.lock` is now authoritative.

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
