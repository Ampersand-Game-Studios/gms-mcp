# GameMaker MCP Tools

This repo provides:
- `gms`: a Python CLI for GameMaker project operations (asset creation, maintenance, runner, etc).
- `gms-mcp`: an MCP server that exposes the same operations as MCP tools (Cursor is the primary example client).
- `gms-mcp-init`: generates shareable MCP config files for a workspace.

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

## CLI usage

Run from a project directory (or pass `--project-root`):

```powershell
gms --version
gms --project-root . asset create script my_function --parent-path "folders/Scripts.yy"
```
