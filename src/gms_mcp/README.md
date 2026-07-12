## GameMaker MCP Server

This folder contains a small **MCP server** that exposes the GameMaker CLI tooling (`gms_helpers`) as MCP tools.

Cursor is the primary example in this repo, but the server is intended to work with any MCP-capable client.

### Why this folder is named `gms_mcp/` (not `mcp/`)

The MCP Python SDK is installed as the **`mcp`** package (`pip install mcp`).
If this repo also had a top-level `mcp/` directory, Python would import the repo folder instead of the SDK, and the server would fail to start.

### What it provides

- A **curated core MCP surface** with opt-in domain toolsets, **safe execution safeguards**, and **bounded local diagnostic logging**:
  - **Assets**: create all supported asset types through the optional `assets` toolset; dependency-aware deletion uses `gm_safe_delete`
  - **Events**: add/remove/duplicate/list/validate/fix
  - **Workflow**: duplicate/rename/**safe-delete**/swap-sprite
  - **Rooms**: ops (duplicate/rename/delete/list), layers (add/remove/list), instances (add/remove/list)
  - **Code Intelligence** (GML symbol analysis for navigation and understanding):
    - `gm_build_index`: Build/rebuild the GML symbol index (cached for performance)
    - `gm_find_definition`: Find definition(s) of a GML symbol (function, enum, macro, globalvar, constructor)
    - `gm_find_references`: Find all references to a symbol across the project
    - `gm_list_symbols`: List all symbols with optional filtering by kind, name, or file
  - **Introspection** (complete support for all asset types including extensions and datafiles):
    - `gm_list_assets`: List all assets by type, name, or folder. Supports filtering by **`asset_type`**, **`name_contains`**, and **`folder_prefix`**. (Includes scripts, objects, sprites, rooms, sounds, fonts, shaders, paths, timelines, tilesets, animcurves, sequences, notes, folders, **particlesystems**, **extensions**, **includedfiles**)
    - `gm_read_asset`: Read complete .yy JSON metadata for any asset
    - `gm_search_references`: Search for patterns (string or regex) across the project with scoping options
    - `gm_get_asset_graph`: Build dependency graph with optional **deep mode** for GML code reference parsing
    - `gm_get_project_stats`: Quick project statistics
  - **Texture Groups** (manage `.yyp` TextureGroups + bulk-assign asset `textureGroupId`):
    - Read-only: `gm_texture_group_list`, `gm_texture_group_read`, `gm_texture_group_members`, `gm_texture_group_scan`
    - Destructive (dry-run aware): `gm_texture_group_create`, `gm_texture_group_update`, `gm_texture_group_rename`, `gm_texture_group_delete`, `gm_texture_group_assign`
  - **MCP Resources** (addressable, cacheable data for fast agent context loading):
    - `gms://project/index`: Complete project structure (assets, folders, room order, configs, audio/texture groups)
    - `gms://project/asset-graph`: Asset dependency graph (structural references)
    - `gms://system/updates`: Check for newer versions of `gms-mcp` (human-readable)
  - **Updates**:
    - `gms-mcp doctor`: Local diagnostics command (package, updates, project detection)
    - `gms-mcp doctor --project`: Project-aware health check
    - `gms-mcp doctor --full`: Full health check including runtime selection and bridge status
    - `gm_check_updates`: Manually check for updates on PyPI and GitHub
    - `gm_project_info`: Includes a cached `updates` summary
  - **Maintenance**: auto + diagnostics/lint/validate-json/list-orphans/prune-missing/validate-paths/dedupe-resources/normalize-names/sync-events/clean-old-files/clean-orphans/fix-issues
  - **Runtime Management**: list/pin/unpin/verify GameMaker runtimes, including LTS2026 channel detection
  - **Runner**: compile/run (with runtime version pinning) + stop/status. Accepts `VM`/`YYC` plus LTS2026 UI aliases `GMS2 VM`/`GMS2 YYC`; GMRT labels are rejected until GameMaker documents Igor CLI support.
  - **TCP Bridge (optional)**: live game commands + log capture via `gm_bridge_install`, `gm_bridge_status`, `gm_run_command`, `gm_run_logs` (see `documentation/BRIDGE.md`). Bridge lifecycle/events stay off MCP stdout so `gm_run(..., enable_bridge=true)` remains stdio-safe.
  - **Project info**: `gm_project_info`

The default `core` profile keeps the tool list focused. Set `GMS_MCP_TOOLSETS` to a comma-separated list of `assets`, `bridge`, `docs`, `events`, `maintenance`, `rooms`, `runtime`, and `texture-groups`, or set it to `all`. Call `gm_capabilities` to inspect the active profile; restart the MCP server after changing it.

### Install

Install the packaged tool once (recommended: `pipx install gms-mcp`), then generate per-workspace config(s) with `gms-mcp-init`.

Manual local diagnostics check:

```bash
gms-mcp doctor
gms-mcp doctor --project
gms-mcp doctor --full
gms-mcp doctor --client codex
gms-mcp doctor --project-root /path/to/project
gms-mcp doctor --client codex --server-name gms-app
gms-mcp doctor --json
```

### Configure (generate configs)

This repo includes a small installer that generates **shareable, user-agnostic** MCP config(s) for your workspace.

- Generate Cursor config (primary example): `gms-mcp-init --cursor`
- Generate Cursor global config (multi-project): `gms-mcp-init --cursor-global`
- Generate other client examples (written to `mcp-configs/*.mcp.json`): `gms-mcp-init --vscode --windsurf --antigravity --openclaw`
- Set up Antigravity global config (recommended): `gms-mcp-init --antigravity-setup`
- Check Antigravity config readiness: `gms-mcp-init --antigravity-check` (secret-like values are redacted in printed payloads)
- Check Antigravity config as JSON: `gms-mcp-init --antigravity-check-json` (secret-like values are redacted in printed payloads)
- One-shot Antigravity app setup: `gms-mcp-init --antigravity-app-setup`
- Generate everything: `gms-mcp-init --all`

Canonical parity interface (all supported clients):

```bash
gms-mcp-init --client <client> --scope <workspace|global> --action <setup|check|check-json|app-setup>
```

See `documentation/CLIENT_SUPPORT_MATRIX.md` for the maintained capability matrix.

### Telemetry

Telemetry is opt-in and default-off.

- Interactive `gms` and `gms-mcp-init` runs may prompt once for consent when no decision exists yet.
- MCP server startup never prompts on stdio.
- Runtime overrides:
  - `--telemetry=inherit|on|off`
  - `GMS_MCP_TELEMETRY=inherit|on|off`
  - `GMS_MCP_TELEMETRY_ENDPOINT=<url>` for local backend testing only
- Local controls:
  - `gms telemetry status`
  - `gms telemetry enable`
  - `gms telemetry enable --with-install-id`
  - `gms telemetry disable`
  - `gms telemetry flush`
  - `gms telemetry clear`

**Environment Auto-detection**: `gms-mcp-init` now automatically detects and writes the following environment variables into the generated config if they are set in your current shell:
- `GMS_MCP_GMS_PATH`
- `GMS_MCP_DEFAULT_TIMEOUT_SECONDS`
- `GMS_MCP_ENABLE_DIRECT`
- `GMS_MCP_IGOR_PROCESSOR_COUNT`

The Cursor config is written to `.cursor/mcp.json` and:

- It uses `${workspaceFolder}` (no usernames / absolute paths)
- By default it launches `gms-mcp` (assumes the tool is on PATH, e.g. via pipx)
- It sets `cwd` to the workspace (prevents "temp project" issues)
- It sets `GM_PROJECT_ROOT` to a detected `.yyp` directory when possible (otherwise defaults to `${workspaceFolder}`)

After changing `.cursor/mcp.json`, **Reload Window** in Cursor to pick up MCP config changes.

### Notes

- **Project resolution**:
  - Tools accept an optional `project_root` parameter. You can pass `.` (default), a path to the repo root, or a path to `gamemaker/`.
  - The server and underlying CLI tools check for both `GM_PROJECT_ROOT` and `PROJECT_ROOT` environment variables (useful for agents / terminal sessions).
- **Execution model / "no silent hangs"**:
  - By default, tools use **isolated subprocess execution**. This ensures they are cancellable, avoid blocking the MCP server, and prevent "silent hangs" on Windows.
  - Subprocess fallbacks isolate the child process from MCP stdin (setting it to `DEVNULL`).
  - Streaming logs via `ctx.log()` is **disabled** during subprocess execution to prevent stdio deadlocks with MCP clients like Cursor.
  - Direct/background runner paths also avoid stdout pollution: bridge lifecycle logging is internal, background Igor output is collected without echoing into the JSON-RPC stream, and spawned local game processes do not inherit MCP stdio.
  - Subprocess invocations write bounded, pruned diagnostic logs under **`.gms_mcp/logs/`**. Direct stdout/stderr capture is also bounded before it enters an MCP response.
  - Tools apply **category-aware default max runtimes** (overrideable) to prevent indefinite blocking. Override globally with `GMS_MCP_DEFAULT_TIMEOUT_SECONDS`.
  - To use typed **direct handlers** instead of the generic CLI subprocess path, set `GMS_MCP_ENABLE_DIRECT=1`. Each call still runs in a disposable, timeout-bounded worker process so helper code cannot change the MCP server's cwd, environment, arguments, or stdio.
  - Direct transaction cancellation is deferred until the worker finishes or reaches its bounded timeout. This prevents caller cancellation from abandoning a half-written GameMaker project; generic CLI subprocess calls remain immediately cancellable with process-tree cleanup.
  - Mutation tools validate typed operation models at the MCP boundary before transactions, direct helper calls, or subprocess fallback. Invalid write arguments return `Invalid MCP tool arguments` and do not retry through another execution path.
  - Real destructive MCP writes run through typed direct handlers only. `prefer_cli=true` is rejected for those calls, and direct infrastructure failures do not fall back to generic CLI execution.
  - To require dry-run mode for destructive operations, set `GMS_MCP_REQUIRE_DRY_RUN=1` (enabled by default for `--antigravity-setup`).
  - To allow a real safe-delete while this policy is enabled, set `GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST=gm_safe_delete`.
  - Post-mutation compile verification defaults to smart mode. Set `GMS_MCP_POST_MUTATION_VERIFY=compile` to compile after every transactional mutation, `smart` to keep the default explicitly, or `off` to disable post-mutation compile verification.
  - In smart mode, high-risk structural mutations compile immediately, while batchable edits like sprite-frame changes create a pending marker in `.gms_mcp/verification_state.json`. Use `gm_verification_status` to inspect it and `gm_verification_flush` to run one compile when the batch is complete.

- **Picking the `gms` executable (Windows shims)**:
  - The server prefers a "real" `gms` when multiple are present on Windows (avoids the WindowsApps shim when possible).
  - To pin the executable, set `GMS_MCP_GMS_PATH` to a full path (e.g. `C:\\Python313\\Scripts\\gms.exe`).

- **Output control (quiet / capture mode)**:
  - Most tools accept `output_mode`: `"full"` (default), `"tail"`, or `"none"`
  - `tail_lines` controls how many lines are returned in `"tail"` mode
  - `quiet=true` is a convenience alias for `"tail"` (unless you explicitly set `output_mode`)
