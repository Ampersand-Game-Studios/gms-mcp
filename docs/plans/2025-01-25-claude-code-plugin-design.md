# Claude Code Plugin Design

## Overview

Add a Claude Code plugin to gms-mcp that provides skills, hooks, and auto-configured MCP server for Claude Code users, while maintaining the universal pip package for all other MCP-compatible tools.

## Goals

- Single repo serves all AI dev tools (Claude Code, Cursor, VSCode, Antigravity, Gemini CLI, Codex CLI)
- Claude Code users get the premium experience: skills, hooks, zero-config MCP
- Non-Claude users unaffected - pip package works as before

## Repository Structure

Following the official Claude Code plugin specification:

```
gms-mcp/
├── .claude-plugin/           # Plugin manifest (required location)
│   └── plugin.json
├── skills/                   # Skills at repo root
│   └── gms-mcp/
│       ├── SKILL.md
│       ├── workflows/        # 18 workflow files
│       └── reference/        # 7 reference files
├── hooks/                    # Hook scripts at repo root
│   ├── session-start.sh
│   └── notify-errors.sh
├── src/
│   ├── gms_helpers/          # CLI library
│   └── gms_mcp/              # MCP server
└── pyproject.toml
```

## Plugin Manifest

Located at `.claude-plugin/plugin.json`:

```json
{
  "name": "gms-mcp",
  "version": "0.2.0",
  "description": "GameMaker development tools for Claude Code - MCP server, skills, and hooks",
  "author": {
    "name": "Callum Lory",
    "url": "https://github.com/Ampersand-Game-Studios"
  },
  "repository": "https://github.com/Ampersand-Game-Studios/gms-mcp",
  "license": "MIT",
  "keywords": ["gamemaker", "gms", "mcp", "game-development"],
  "skills": "./skills/",
  "mcpServers": {
    "gms-mcp": {
      "command": "uvx",
      "args": ["gms-mcp"],
      "env": {}
    }
  },
  "hooks": {
    "SessionStart": [...],
    "PostToolUseFailure": [...]
  }
}
```

### MCP Server Configuration

Inline in plugin.json using `uvx` for zero-friction setup - auto-installs from PyPI.

### Project Root Detection

1. On MCP server startup, scan working directory for `.yyp` files
2. If exactly one found: use its parent as `GM_PROJECT_ROOT`
3. If multiple found: server returns error listing them
4. If none found: server operates in "no project" mode

## Hooks

Using official Claude Code hook events:

### SessionStart Hook

Triggers: When Claude Code session starts

```json
{
  "SessionStart": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh",
          "timeout": 30
        }
      ]
    }
  ]
}
```

Actions:
- Check if GameMaker project exists (.yyp file)
- Check for gms-mcp updates
- Report bridge installation status

### PostToolUseFailure Hook

Triggers: When gm_run_start or gm_compile fails

```json
{
  "PostToolUseFailure": [
    {
      "matcher": "gm_run_start|gm_compile",
      "hooks": [
        {
          "type": "command",
          "command": "${CLAUDE_PLUGIN_ROOT}/hooks/notify-errors.sh",
          "timeout": 10
        }
      ]
    }
  ]
}
```

Actions:
- Parse compiler output for errors
- Surface in user-friendly format

## Installation Flows

### Claude Code Users

```
/install-plugin github:Ampersand-Game-Studios/gms-mcp
```

Or via CLI:
```bash
claude plugin install github:Ampersand-Game-Studios/gms-mcp
```

Result:
- Skills immediately available
- MCP server auto-configured via uvx
- Hooks activate for GameMaker workspaces

### Non-Claude Users (Cursor, VSCode, etc.)

```bash
pip install gms-mcp
gms-mcp-init --cursor  # or --vscode, etc.
```

Unchanged from current behavior.

## Migration

### What Moved
- `src/gms_helpers/skills/gms-mcp/` → `skills/gms-mcp/`

### What's New
- `.claude-plugin/plugin.json` - Plugin manifest with inline MCP and hooks config
- `hooks/` directory with shell scripts

### Breaking Changes
None. Existing pip users unaffected.

## Key Specifications

Based on official Claude Code plugin documentation:

- Plugin manifest must be at `.claude-plugin/plugin.json`
- Hook events use PascalCase: `SessionStart`, `PostToolUseFailure`
- Use `${CLAUDE_PLUGIN_ROOT}` for paths in hooks
- MCP config can be inline in plugin.json under `mcpServers`
- Skills directory referenced via `"skills": "./skills/"`
