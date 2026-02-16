# Codex Workspace-Scoped MCP Policy

This document defines the standard Codex setup for GameMaker projects in this workspace.

## Goals

- Keep GameMaker MCP tools out of unrelated chats.
- Use one MCP server name (`gms`) across all projects.
- Pin `GM_PROJECT_ROOT` per repository at workspace scope.

## Required Configuration Model

1. Do not keep `gms` in global Codex MCP config (`~/.codex/config.toml`).
2. For each GameMaker repository root, create `.codex/mcp.toml` with:

```toml
[mcp_servers.gms]
command = "gms-mcp"
args = []

[mcp_servers.gms.env]
PYTHONUNBUFFERED = "1"
GM_PROJECT_ROOT = "<repo-specific GameMaker folder>"
```

3. Avoid project-specific global aliases like `gms-winbo`, `gms-local`, or `gms-<project>`.
   Keep those only for short-lived debugging if truly needed.

## Onboarding Rule for New GameMaker Repos

Run this once from `gms-mcp`:

```bash
.venv/bin/gms-mcp-init \
  --workspace-root "<repo-root>" \
  --server-name gms \
  --gm-project-root "<dir-containing-target-yyp>" \
  --codex \
  --non-interactive
```

Then validate:

```bash
.venv/bin/gms-mcp-init \
  --workspace-root "<repo-root>" \
  --server-name gms \
  --codex-check-json
```

Acceptance criteria:

- `active.scope` is `workspace`
- `ready` is `true`
- `active.entry.env.GM_PROJECT_ROOT` is the intended project directory

## Audit Command

Use the audit script to verify coverage and drift:

```bash
scripts/audit_codex_workspace_mcp.sh --scan-root "$HOME/Documents"
```

Strict mode treats global alias warnings as failures:

```bash
scripts/audit_codex_workspace_mcp.sh --scan-root "$HOME/Documents" --strict
```

What it checks:

- Global Codex config does not define `[mcp_servers.gms]`
- Workspace `.codex/mcp.toml` exists for every discovered GameMaker repo
- Workspace config includes `[mcp_servers.gms]` and `GM_PROJECT_ROOT`
- `GM_PROJECT_ROOT` matches a discovered non-prefab `.yyp` directory in that repo

## Session Reload Note

After MCP config changes, start a new chat (or reload the app/session) before validating tool availability.
Tool lists are resolved at session start, so old chats may still show stale MCP server namespaces.
