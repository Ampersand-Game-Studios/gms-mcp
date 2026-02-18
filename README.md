# GameMaker MCP Tools
[![CI](https://github.com/Ampersand-Game-Studios/gms-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Ampersand-Game-Studios/gms-mcp/actions/workflows/ci.yml)

## Project Features

- `gms`: a Python CLI for GameMaker project operations (asset creation, maintenance, runner, etc).
- `gms-mcp`: an MCP server that exposes the same operations as MCP tools (Cursor is the primary example client).
- **TCP Bridge (optional)**: live, bidirectional game communication (commands + log capture) via `gm_bridge_install`, `gm_run_command`, and `gm_run_logs`. See `documentation/BRIDGE.md`.
- **Reliability-First Architecture**: Custom exception hierarchy, typed result objects, and an execution policy manager replace monolithic exit calls and raw dictionaries. This enables structured error handling, consistent tool integration, and optimized performance (Fast assets, Resilient runner).
- **Health & Diagnostics**: `gm_mcp_health` provides a one-click diagnostic tool to verify the local GameMaker environment. `gm_diagnostics` provides structured, machine-readable project diagnostics (JSON, naming, orphans, references) compatible with IDE problem panels.
- **Runtime Management**: `gm_runtime_list`, `gm_runtime_pin`, and `gm_runtime_verify` allow precise control over which GameMaker runtime version is used for builds and execution.
- **Cross-Platform Runner Defaults**: `gm_run` / `gm_compile` now default to the host OS target platform (`macOS`, `Linux`, or `Windows`) when not explicitly provided.
- **macOS Runner Launch Support**: temp-output runs now detect and launch macOS `.app` bundles by resolving the executable in `Contents/MacOS/`.
- **GML Symbol Indexing & Code Intelligence**: `gm_build_index`, `gm_find_definition`, `gm_find_references`, and `gm_list_symbols` provide deep, fast, and filtered code analysis (definitions and cross-file references).
- **Introspection**: complete project inspection with support for all asset types (including extensions and datafiles).
- **MCP Resources**: addressable project index and asset graph for high-performance agent context loading.
- `gms-mcp-init`: generates shareable MCP config files for a workspace. Now auto-detects environment variables like `GMS_MCP_GMS_PATH` to include in the generated config.

## Install (recommended: pipx)

```bash
pipx install gms-mcp
```

PowerShell equivalent:

```powershell
pipx install gms-mcp
```

## Claude Code Plugin

For Claude Code users, install the plugin for the best experience:

```
/install-plugin github:Ampersand-Game-Studios/gms-mcp
```

This provides:
- **Skills**: 18 workflow guides + 7 reference docs
- **Hooks**: Automatic update checks and error notifications
- **MCP Server**: Auto-configured via uvx (no pip install needed)

### For Other Tools (Cursor, VSCode, OpenClaw, etc.)

```bash
pip install gms-mcp
gms-mcp-init --cursor  # or --vscode, --windsurf, --openclaw, etc.
```

For skill packs, OpenClaw users can install to user or workspace scope:

```bash
gms skills install --openclaw            # user scope: ~/.openclaw/skills/
gms skills install --openclaw --project  # workspace scope: ./skills/
```

Note: `.openclaw/openclaw.json` is for settings. Workspace skills are loaded from `./skills/`.

### For Codex

```bash
gms-mcp-init --codex
```

This writes a workspace `.codex/mcp.toml` file and prints the `codex mcp add` registration command.

Global config mode writes directly to `~/.codex/config.toml` (merging server entries).

Use the printed command directly, or copy `.codex/mcp.toml` content into the `[mcp_servers]` section of your `~/.codex/config.toml`.

Codex helpers:
- `gms-mcp-init --codex-check` prints detected Codex config paths and active server entry.
- `gms-mcp-init --codex-check-json` prints the same check output in machine-readable JSON.
- `gms-mcp-init --codex-dry-run-only` prints final merged payloads for workspace + global Codex config without writing files.
- `gms-mcp-init --codex-app-setup` runs one-shot Codex app setup: writes workspace config, previews global merge, then prints check + readiness summary.

## Local Development Setup

If you are working on the `gms-mcp` codebase itself, follow these steps to set up a local development environment:

1.  **Clone and install in editable mode**:
    ```bash
    git checkout dev
    python3.12 -m venv .venv
    source .venv/bin/activate
    python3.12 -m pip install -e ".[dev]"
    ```
    `gms-mcp` requires Python `3.10+`; we recommend Python `3.12` for local development.

2.  **Run the full local test suite**:
    ```bash
    PYTHONPATH=src python3.12 cli/tests/python/run_all_tests.py
    ```

3.  **Initialize local and global MCP servers for testing**:
    We recommend setting up two separate MCP server configurations in Cursor to test your changes:
    
    *   **Global (`gms-global`)**: For general use across all your GameMaker projects.
    *   **Local (`gms-local`)**: Specifically for testing your current changes to the server.

    Run these commands from the project root (zsh/bash):
    ```bash
    # Global setup (names it 'gms-global' in Cursor)
    gms-mcp-init --cursor-global --server-name gms-global --mode python-module --python python3 --non-interactive

    # Local setup (names it 'gms-local' in Cursor)
    gms-mcp-init --cursor --server-name gms-local --mode python-module --python python3 --non-interactive
    ```

    PowerShell equivalent:

    ```powershell
    # Global setup (names it 'gms-global' in Cursor)
    gms-mcp-init --cursor-global --server-name gms-global --mode python-module --python python --non-interactive

    # Local setup (names it 'gms-local' in Cursor)
    gms-mcp-init --cursor --server-name gms-local --mode python-module --python python --non-interactive
    ```

4.  **Verify in Cursor**:
    Go to **Cursor Settings > Features > MCP** to see your new servers. You may need to click "Reload" or restart Cursor to see changes.

## Publishing (maintainers)

Publishing is automated via GitHub Actions (PyPI Trusted Publishing) on every push to `main` and on tags `v*`.
See `RELEASING.md` for the one-time PyPI setup and the first manual upload helper scripts.

## CI Coverage

- Core CI runs on Ubuntu and Windows across Python `3.11`-`3.13`.
- Runner/session regression tests also run on macOS across Python `3.11`-`3.13`, including a mockless smoke test that builds a real `.app` bundle structure and validates executable path resolution.

### Quality Reports

Quality reports are generated during CI and published as `quality-reports-*` artifacts.

- `TEST_COVERAGE_REPORT.md`
- `MCP_TOOL_VALIDATION_REPORT.md`
- `coverage.xml`
- `pytest_results.xml`
- `quality_summary.json`

You can regenerate these locally with:

```bash
python scripts/generate_quality_reports.py
```

Use `--skip-test-run` to regenerate from existing CI artifacts:

```bash
python scripts/generate_quality_reports.py --skip-test-run --junit-xml build/reports/pytest_results.xml --coverage-xml build/reports/coverage.xml
```

## X (Twitter) posting on `main`

This repo can post to X automatically when `main` is updated.

- **Personality / voice**: `.github/x-personality.md`
- **Tweet staging file**: `.github/next_tweet.txt`

### How it works

- When a commit lands on `main`, GitHub Actions reads `.github/next_tweet.txt`.
- If it contains the placeholder text (or is empty), it **skips posting**.
- If it contains a real tweet, it posts to X and then **clears the file** back to the placeholder.

### Maintainer flow (dev -> pre-release -> main)

Because this repo promotes changes `dev` -> `pre-release` -> `main`, prepare the tweet during the `pre-release` -> `main` PR:

- Update `.github/next_tweet.txt` with the tweet (following `.github/x-personality.md`)
- Merge to `main`

## Use with a GameMaker project (multi-project friendly)

Run this inside each GameMaker project workspace (or repo) to generate config:

```bash
gms-mcp-init --cursor
```

This writes `.cursor/mcp.json` and attempts to auto-detect the `.yyp` location to set `GM_PROJECT_ROOT`.

For a one-time setup that works across many projects, write Cursor's global config instead:

```bash
gms-mcp-init --cursor-global
```

Generate a Codex config from the current workspace:

```bash
gms-mcp-init --codex
```

Generate a global Codex entry in `~/.codex/config.toml`:

```bash
gms-mcp-init --codex-global
```

Global mode merges with existing entries so it is safe to keep multiple MCP servers in the same file.

Inspect current Codex config resolution:

```bash
gms-mcp-init --codex-check
```

Preview final merged Codex payloads for local + global without writing:

```bash
gms-mcp-init --codex-dry-run-only
```

Print Codex check output as JSON (useful for app automation):

```bash
gms-mcp-init --codex-check-json
```

One-shot Codex app setup (recommended for new workspaces):

```bash
gms-mcp-init --codex-app-setup
```

### Codex App Quickstart

1. Run `gms-mcp-init --codex-app-setup` in your GameMaker workspace.
2. Confirm the output says `Ready for Codex app: yes`.
3. If needed, run `gms-mcp-init --codex-check-json` and verify `active.scope` is `workspace`.
4. Use `gms-mcp-init --codex-dry-run-only` before changing global config to preview merged TOML safely.

## Canonical Client Workflow

All clients now support the same canonical action surface:

```bash
gms-mcp-init \
  --client <cursor|codex|claude-code|claude-desktop|antigravity|gemini|vscode|windsurf|openclaw|generic> \
  --scope <workspace|global> \
  --action <setup|check|check-json|app-setup>
```

Optional:
- `--config-path /custom/path` to override default config location
- `--safe-profile` to enforce conservative env defaults

Examples:

```bash
# Cursor setup + readiness check
gms-mcp-init --client cursor --scope workspace --action app-setup

# Codex machine-readable readiness
gms-mcp-init --client codex --scope workspace --action check-json

# Claude Desktop global plugin sync
gms-mcp-init --client claude-desktop --scope global --action setup

# Gemini alias (Antigravity path)
gms-mcp-init --client gemini --scope global --action app-setup

# OpenClaw app setup + workspace skills install
gms-mcp-init --client openclaw --scope workspace --action app-setup \
  --openclaw-install-skills --openclaw-skills-project
```

For parity status and supported defaults, see `documentation/CLIENT_SUPPORT_MATRIX.md`.

Generate example configs for other MCP-capable clients:

```bash
gms-mcp-init --vscode --windsurf --antigravity --openclaw
```

Set up Antigravity global config (recommended):

```bash
gms-mcp-init --antigravity-setup
```

This merges into `~/.gemini/antigravity/mcp_config.json`, writes atomically, creates a timestamped backup on overwrite, and enables a conservative safety profile by default:
- `GMS_MCP_ENABLE_DIRECT=0`
- `GMS_MCP_REQUIRE_DRY_RUN=1`

Check Antigravity readiness:

```bash
gms-mcp-init --antigravity-check
```

Print Antigravity check output as JSON:

```bash
gms-mcp-init --antigravity-check-json
```

One-shot Antigravity app setup:

```bash
gms-mcp-init --antigravity-app-setup
```

Use a custom Antigravity config path:

```bash
gms-mcp-init --antigravity-setup --antigravity-config-path /path/to/mcp_config.json
```

Opt in to the conservative safety profile for Antigravity example configs too:

```bash
gms-mcp-init --antigravity --safe-profile
```

When `GMS_MCP_REQUIRE_DRY_RUN=1` is set, you can allow specific destructive tools with:

```bash
export GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST=gm_asset_delete,gm_workflow_delete
```

Or generate everything at once:

```bash
gms-mcp-init --all
```

## Monorepos / multiple `.yyp`

If multiple `.yyp` projects are detected in a workspace:
- `gms-mcp-init` will warn and (when interactive) prompt you to pick one.
- In non-interactive environments, it defaults `GM_PROJECT_ROOT` to `${workspaceFolder}` (safe).

Force a specific project root:

```bash
gms-mcp-init --cursor --gm-project-root path/to/project
```

Preview output without writing files:

```bash
gms-mcp-init --cursor --dry-run
```

## Code Intelligence & Introspection

The MCP server provides comprehensive project analysis capabilities:

### GML Symbol Indexing (`gm_build_index`)
Build a high-performance index of all functions, enums, macros, and global variables in the project. This is required for advanced code intelligence tools.

### Symbol Definition (`gm_find_definition`)
Find the exact location and docstrings for any GML symbol in your project.

### Find References (`gm_find_references`)
Search for all usages of a specific function or variable across your entire codebase.

### List Symbols (`gm_list_symbols`)
List all project symbols with filtering by type, name substring, or file path.

### Asset Listing (`gm_list_assets`)
List all assets in your project, optionally filtered by type:
- **Supported types**: script, object, sprite, room, sound, font, shader, path, timeline, tileset, animcurve, sequence, note, folder, **extension**, **includedfile** (datafiles)

### Asset Reading (`gm_read_asset`)
Read the complete `.yy` JSON metadata for any asset by name or path.

### Reference Search (`gm_search_references`)
Search for patterns across project files with:
- **Scopes**: `all`, `gml`, `yy`, `scripts`, `objects`, `extensions`, `datafiles`
- **Modes**: literal string or regex
- **Options**: case sensitivity, max results

### Asset Graph (`gm_get_asset_graph`)
Build a dependency graph of assets with two modes:
- **Shallow (fast)**: Parses `.yy` files for structural references (parent objects, sprites, etc.)
- **Deep (complete)**: Also scans all GML code for runtime references like `instance_create`, `sprite_index`, `audio_play_sound`, etc.

### Texture Groups (`gm_texture_group_*`)
Create, inspect, and edit `.yyp` `TextureGroups`, plus bulk-assign assets (sprites/fonts/tilesets/etc) via `textureGroupId`.

Read-only tools:
- `gm_texture_group_list`: list texture groups + available configs (desktop/android/ios/etc)
- `gm_texture_group_read`: read a single texture group entry
- `gm_texture_group_members`: list assets in a group (top-level + ConfigValues overrides)
- `gm_texture_group_scan`: report missing groups referenced + mismatches (top-level vs config override)

Destructive tools (all support `dry_run=true`):
- `gm_texture_group_create`: clone an existing template group (default: `Default`)
- `gm_texture_group_update`: patch fields on a group (optionally per config via `ConfigValues`)
- `gm_texture_group_rename`: rename a group and rewrite asset references
- `gm_texture_group_delete`: blocks by default if referenced unless `reassign_to` is provided
- `gm_texture_group_assign`: bulk-assign assets by explicit list or filters

Config scope defaults:
- Assignment updates an asset's top-level `textureGroupId` **only when it is a dict** (null is left as-is).
- If `configs` is omitted, assignment updates only **existing** `ConfigValues` entries; pass `configs=[...]` to create explicit overrides.

### MCP Resources
Pre-built, cacheable project data for agents:
- `gms://project/index`: Complete project structure (assets, folders, room order, configs, audio/texture groups, IDE version)
- `gms://project/asset-graph`: Asset dependency graph
- `gms://system/updates`: Returns a human-readable message if a newer version of `gms-mcp` is available on PyPI or GitHub.

### Update Notifier
The server automatically checks for updates on startup and during common operations:
- **Tool**: `gm_check_updates` returns structured update info.
- **Auto-check**: `gm_project_info` includes an `updates` field.
- **Resource**: `gms://system/updates` provides a quick text status.

## CLI usage

Run from a project directory (or pass `--project-root`):

```bash
gms --version
gms --project-root . asset create script my_function --parent-path "folders/Scripts.yy"
gms --project-root . texture-groups list
gms --project-root . texture-groups assign game --type sprite --folder-prefix sprites/ --dry-run
```
