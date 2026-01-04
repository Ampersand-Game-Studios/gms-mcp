## GameMaker MCP Server

This folder contains a small **MCP server** that exposes the GameMaker CLI tooling (`gms_helpers`) as MCP tools.

Cursor is the primary example in this repo, but the server is intended to work with any MCP-capable client.

### Why this folder is named `gms_mcp/` (not `mcp/`)

The MCP Python SDK is installed as the **`mcp`** package (`pip install mcp`).
If this repo also had a top-level `mcp/` directory, Python would import the repo folder instead of the SDK, and the server would fail to start.

### What it provides

- **Full `gms` parity** exposed as MCP tools, with **safe execution safeguards** and **local diagnostic logging**:
  - **Assets**: create *all* supported asset types + delete
  - **Events**: add/remove/duplicate/list/validate/fix
  - **Workflow**: duplicate/rename/delete/swap-sprite
  - **Rooms**: ops (duplicate/rename/delete/list), layers (add/remove/list), instances (add/remove/list)
  - **Maintenance**: auto + lint/validate-json/list-orphans/prune-missing/validate-paths/dedupe-resources/sync-events/clean-old-files/clean-orphans/fix-issues
  - **Runner**: compile/run + stop/status
  - **Escape hatch**: `gm_cli` (run arbitrary `gms` args)
  - **Project info**: `gm_project_info`

### Install

Install the packaged tool once (recommended: `pipx install gms-mcp`), then generate per-workspace config(s) with `gms-mcp-init`.

### Configure (generate configs)

This repo includes a small installer that generates **shareable, user-agnostic** MCP config(s) for your workspace.

- Generate Cursor config (primary example): `gms-mcp-init --cursor`
- Generate Cursor global config (multi-project): `gms-mcp-init --cursor-global`
- Generate other client examples (written to `mcp-configs/*.mcp.json`): `gms-mcp-init --vscode --windsurf --antigravity`
- Generate everything: `gms-mcp-init --all`

The Cursor config is written to `.cursor/mcp.json` and:

- It uses `${workspaceFolder}` (no usernames / absolute paths)
- By default it launches `gms-mcp` (assumes the tool is on PATH, e.g. via pipx)
- It sets `cwd` to the workspace (prevents “temp project” issues)
- It sets `GM_PROJECT_ROOT` to a detected `.yyp` directory when possible (otherwise defaults to `${workspaceFolder}`)

After changing `.cursor/mcp.json`, **Reload Window** in Cursor to pick up MCP config changes.

### Notes

- **Project resolution**:
  - Tools accept an optional `project_root` parameter. You can pass `.` (default), a path to the repo root, or a path to `gamemaker/`.
  - The server and underlying CLI tools check for both `GM_PROJECT_ROOT` and `PROJECT_ROOT` environment variables (useful for agents / terminal sessions).
- **Execution model / “no silent hangs”**:
  - By default, tools use **isolated subprocess execution**. This ensures they are cancellable, avoid blocking the MCP server, and prevent "silent hangs" on Windows.
  - Subprocess execution (via `gm_cli` or default fallback) isolates the child process from MCP stdin (setting it to `DEVNULL`).
  - Streaming logs via `ctx.log()` is **disabled** during subprocess execution to prevent stdio deadlocks with MCP clients like Cursor.
  - Every invocation writes a complete diagnostic log file under **`.gms_mcp/logs/`** in the resolved project directory.
  - Tools apply **category-aware default max runtimes** (overrideable) to prevent indefinite blocking. Override globally with `GMS_MCP_DEFAULT_TIMEOUT_SECONDS`.
  - To bypass subprocess overhead and use faster **in-process execution**, set `GMS_MCP_ENABLE_DIRECT=1`. This is faster but less resilient to hangs in library code.

- **Picking the `gms` executable (Windows shims)**:
  - The server prefers a “real” `gms` when multiple are present on Windows (avoids the WindowsApps shim when possible).
  - To pin the executable, set `GMS_MCP_GMS_PATH` to a full path (e.g. `C:\\Python313\\Scripts\\gms.exe`).

- **Output control (quiet / capture mode)**:
  - Most tools accept `output_mode`: `"full"` (default), `"tail"`, or `"none"`
  - `tail_lines` controls how many lines are returned in `"tail"` mode
  - `quiet=true` is a convenience alias for `"tail"` (unless you explicitly set `output_mode`)
