# GameMaker MCP Tools

## Project Features

- `gms`: a Python CLI for GameMaker project operations (asset creation, maintenance, runner, etc).
- `gms-mcp`: an MCP server that exposes the same operations as MCP tools (Cursor is the primary example client).
- **Reliability-First Architecture**: Custom exception hierarchy, typed result objects, and an execution policy manager replace monolithic exit calls and raw dictionaries. This enables structured error handling, consistent tool integration, and optimized performance (Fast assets, Resilient runner).
- **Health & Diagnostics**: `gm_mcp_health` provides a one-click diagnostic tool to verify the local GameMaker environment. `gm_diagnostics` provides structured, machine-readable project diagnostics (JSON, naming, orphans, references) compatible with IDE problem panels.
- **Runtime Management**: `gm_runtime_list`, `gm_runtime_pin`, and `gm_runtime_verify` allow precise control over which GameMaker runtime version is used for builds and execution.
- **GML Symbol Indexing & Code Intelligence**: `gm_build_index`, `gm_find_definition`, `gm_find_references`, and `gm_list_symbols` provide deep, fast, and filtered code analysis (definitions and cross-file references).
- **Introspection**: complete project inspection with support for all asset types (including extensions and datafiles).
- **MCP Resources**: addressable project index and asset graph for high-performance agent context loading.
- `gms-mcp-init`: generates shareable MCP config files for a workspace. Now auto-detects environment variables like `GMS_MCP_GMS_PATH` to include in the generated config.

## Install (recommended: pipx)

```powershell
pipx install gms-mcp
```

## Local Development Setup

If you are working on the `gms-mcp` codebase itself, follow these steps to set up a local development environment:

1.  **Clone and install in editable mode**:
    ```powershell
    git checkout dev
    pip install -e .
    ```

2.  **Initialize local and global MCP servers for testing**:
    We recommend setting up two separate MCP server configurations in Cursor to test your changes:
    
    *   **Global (`gms-global`)**: For general use across all your GameMaker projects.
    *   **Local (`gms-local`)**: Specifically for testing your current changes to the server.

    Run these commands from the project root:
    ```powershell
    # Global setup (names it 'gms-global' in Cursor)
    gms-mcp-init --cursor-global --server-name gms-global --mode python-module --python python --non-interactive

    # Local setup (names it 'gms-local' in Cursor)
    gms-mcp-init --cursor --server-name gms-local --mode python-module --python python --non-interactive
    ```

3.  **Verify in Cursor**:
    Go to **Cursor Settings > Features > MCP** to see your new servers. You may need to click "Reload" or restart Cursor to see changes.

## Publishing (maintainers)

Publishing is automated via GitHub Actions (PyPI Trusted Publishing) on every push to `main` and on tags `v*`.
See `RELEASING.md` for the one-time PyPI setup and the first manual upload helper scripts.

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

```powershell
gms-mcp-init --cursor
```

This writes `.cursor/mcp.json` and attempts to auto-detect the `.yyp` location to set `GM_PROJECT_ROOT`.

For a one-time setup that works across many projects, write Cursor's global config instead:

```powershell
gms-mcp-init --cursor-global
```

Generate example configs for other MCP-capable clients:

```powershell
gms-mcp-init --vscode --windsurf --antigravity
```

Or generate everything at once:

```powershell
gms-mcp-init --all
```

## Monorepos / multiple `.yyp`

If multiple `.yyp` projects are detected in a workspace:
- `gms-mcp-init` will warn and (when interactive) prompt you to pick one.
- In non-interactive environments, it defaults `GM_PROJECT_ROOT` to `${workspaceFolder}` (safe).

Force a specific project root:

```powershell
gms-mcp-init --cursor --gm-project-root path\\to\\project
```

Preview output without writing files:

```powershell
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

### MCP Resources
Pre-built, cacheable project data for agents:
- `gms://project/index`: Complete project structure (assets, folders, room order, audio/texture groups, IDE version)
- `gms://project/asset-graph`: Asset dependency graph
- `gms://system/updates`: Returns a human-readable message if a newer version of `gms-mcp` is available on PyPI or GitHub.

### Update Notifier
The server automatically checks for updates on startup and during common operations:
- **Tool**: `gm_check_updates` returns structured update info.
- **Auto-check**: `gm_project_info` includes an `updates` field.
- **Resource**: `gms://system/updates` provides a quick text status.

## CLI usage

Run from a project directory (or pass `--project-root`):

```powershell
gms --version
gms --project-root . asset create script my_function --parent-path "folders/Scripts.yy"
```
