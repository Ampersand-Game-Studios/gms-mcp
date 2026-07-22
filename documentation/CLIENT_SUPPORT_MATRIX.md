# MCP Client Support Matrix

This matrix tracks parity coverage for `gms-mcp-init` canonical client workflows.

## Canonical Interface

Use canonical flags for all clients:

```bash
gms-mcp-init --client <client> --scope <workspace|global> --action <setup|check|check-json|app-setup>
```

Optional:
- `--config-path <path>` to override default location
- `--safe-profile` to enforce conservative env defaults

`check-json` returns a stable payload contract:
- `ok`, `client`, `scope`, `server_name`
- `config.path`, `config.exists`, `config.entry`
- `active.scope`, `active.path`, `active.entry`
- `ready`, `problems[]`, `not_applicable`

## Client Matrix

| Client | Aliases | Workspace | Global | Config Format | Actions |
|---|---|---|---|---|---|
| `cursor` | - | yes | yes | JSON (`mcpServers`) | setup, check, check-json, app-setup |
| `codex` | - | yes | yes | TOML (`mcp_servers`) | setup, check, check-json, app-setup |
| `claude-code` | `claude` | yes | no | `.mcp.json` | setup, check, check-json, app-setup |
| `claude-desktop` | `claude-code-global` | no | yes | plugin dir + `.mcp.json` | setup, check, check-json, app-setup |
| `antigravity` | `gemini` | yes | yes | JSON (`mcpServers`) | setup, check, check-json, app-setup |
| `vscode` | - | yes | yes | JSON (`mcpServers`) | setup, check, check-json, app-setup |
| `windsurf` | - | yes | yes | JSON (`mcpServers`) | setup, check, check-json, app-setup |
| `openclaw` | - | yes | yes | JSON (`mcpServers`) | setup, check, check-json, app-setup |
| `generic` | - | yes | yes | JSON (`mcpServers`) | setup, check, check-json, app-setup |

## Not Applicable Semantics

If a client does not support a scope, `check-json` returns:
- `ok: true`
- `not_applicable: true`
- `ready: false`
- `problems[]` with a concrete reason

This keeps parity reporting deterministic while respecting client limits.

## OpenClaw App Setup Extras

OpenClaw app setup can optionally install bundled skills:

```bash
gms-mcp-init \
  --client openclaw \
  --scope workspace \
  --action app-setup \
  --openclaw-install-skills \
  --openclaw-skills-project
```

## CI Enforcement

Parity checks are validated by:
- `cli/tests/python/test_install_polish.py`
- `cli/tests/python/test_install_parity.py`

macOS CI includes parity install tests in addition to runner/session tests.
