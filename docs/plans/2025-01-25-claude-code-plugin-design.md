# Claude Code Plugin Design

## Overview

Add a Claude Code plugin to gms-mcp that provides skills, hooks, and auto-configured MCP server for Claude Code users, while maintaining the universal pip package for all other MCP-compatible tools.

## Goals

- Single repo serves all AI dev tools (Claude Code, Cursor, VSCode, Antigravity, Gemini CLI, Codex CLI)
- Claude Code users get the premium experience: skills, hooks, zero-config MCP
- Non-Claude users unaffected - pip package works as before

## Repository Structure

```
gms-mcp/
├── src/
│   ├── gms_helpers/          # CLI library
│   ├── gms_mcp/              # MCP server
│   └── ...
├── plugin/                    # Claude Code plugin
│   ├── skills/
│   │   └── gms-mcp/
│   │       ├── SKILL.md
│   │       ├── workflows/    # 18 workflow files
│   │       └── reference/    # 7 reference files
│   ├── hooks/
│   │   ├── session-start.sh  # Update check + bridge status
│   │   └── notify-errors.sh  # Surface compile errors
│   ├── mcp.json              # MCP server config (uvx)
│   └── plugin.json           # Plugin manifest
├── pyproject.toml            # pip package config
└── ...
```

## MCP Configuration

The plugin's `mcp.json` uses `uvx` for zero-friction setup:

```json
{
  "mcpServers": {
    "gms-mcp": {
      "command": "uvx",
      "args": ["gms-mcp"],
      "env": {}
    }
  }
}
```

### Project Root Detection

1. On MCP server startup, scan working directory for `.yyp` files
2. If exactly one found: use its parent as `GM_PROJECT_ROOT`
3. If multiple found: server returns error listing them, session-start hook prompts user to choose
4. If none found: server operates in "no project" mode, hook notifies user

## Hooks

### Session Start Check (`hooks/session-start.sh`)

Triggers when: A `.yyp` file exists in the workspace

Actions:
- Check for gms-mcp updates via `uvx gms-mcp --check-updates`
- If bridge installed, report connection status
- Output brief status message

Example output:
```
[gms-mcp] v0.2.0 available (you have v0.1.1)
[gms-mcp] Bridge: not installed
```

### Error Notification (`hooks/notify-errors.sh`)

Triggers when: `gm_run_start` or `gm_compile` tool returns errors

Actions:
- Parse compiler output for errors/warnings
- Surface in user-friendly format

Example output:
```
[gms-mcp] Compile failed:
  objects/o_player/Create_0.gml:15 - variable 'speed' not declared
```

## Plugin Manifest

```json
{
  "name": "gms-mcp",
  "version": "0.2.0",
  "description": "GameMaker development tools for Claude Code",
  "author": "your-name",
  "repository": "github:your-username/gms-mcp",
  "requirements": {
    "uv": true
  }
}
```

## Installation Flows

### Claude Code Users

```
/install-plugin github:your-username/gms-mcp
```

Result:
- Skills immediately available
- MCP server auto-configured
- Hooks activate for GameMaker workspaces

### Non-Claude Users (Cursor, VSCode, etc.)

```bash
pip install gms-mcp
gms-mcp-init --cursor  # or --vscode, etc.
```

Unchanged from current behavior.

## Migration

### What Moves
- `src/gms_helpers/skills/gms-mcp/` → `plugin/skills/gms-mcp/`

### What Stays
- `gms skills install/list/uninstall` commands (now copy from `plugin/skills/`)

### What's New
- `plugin/` directory with hooks, mcp.json, plugin.json

### Version Sync
- `plugin.json` version matches `pyproject.toml` version

### Breaking Changes
None. Existing pip users unaffected.

## Implementation Steps

1. Create `plugin/` directory structure
2. Move skills from `src/gms_helpers/skills/` to `plugin/skills/`
3. Update `gms skills` commands to reference new location
4. Create `plugin/mcp.json` with uvx configuration
5. Create `plugin/plugin.json` manifest
6. Implement `hooks/session-start.sh`
7. Implement `hooks/notify-errors.sh`
8. Update documentation (README, CHANGELOG)
9. Test plugin installation via `/install-plugin`
