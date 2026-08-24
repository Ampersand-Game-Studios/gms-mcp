# MCP Client Support Matrix

This matrix tracks parity coverage for `gms-mcp-init` canonical client workflows and separates installer support from runtime MCP capabilities.

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

All generated configurations use `stdio`. Streamable HTTP is a manually configured, local-only alternative; see [MCP Server Runtime](CONFIGURATION.md#mcp-server-runtime).

## Runtime Capability Contract

Client products evolve independently, so installer support does not imply that every optional MCP SDK v2 feature is rendered by that client. GMS-MCP negotiates capabilities at connection time and preserves the base tool experience when an optional client capability is absent.

| Server behavior | Protocol/capability needed | Behavior without it |
|---|---|---|
| Named tools, resources, prompts, and structured tool payloads | Base MCP support | Required; the client is not compatible without the base MCP contract |
| Legacy tool contract | MCP `2025-11-25` | Same registered tool names and core capability payload as modern mode |
| Cache hints | MCP `2026-07-28` cache fields | Results still work; the client receives no negotiated cache benefit |
| Structured `is_error` failures | MCP `2026-07-28` result model | Legacy clients retain the compatible tool result envelope |
| Live project-resource updates | Resource subscriptions | Resources remain readable but are not pushed after changes |
| Asset and room URI templates | Resource-template support | Fixed project resources and tools remain available |
| Project dashboard UI | MCP Apps extension | `gm_project_dashboard` returns equivalent text and structured data |
| Resolve safety choices | MCP `2026-07-28` input-required handling plus the requested input capability | Normal calls remain automatic; exceptional mutations stop without writing until the required choice can be resolved |
| Local Streamable HTTP | Client Streamable HTTP transport support | Use the generated `stdio` configuration |

GMS-MCP's automated compatibility suite verifies the modern MCP `2026-07-28` mode, legacy `2025-11-25` mode, real stdio transport, local Streamable HTTP, resource subscriptions, MCP Apps fallback, OpenTelemetry middleware, and multi-round Resolve flows. It does not certify every released version of every client product.

### Checking a Client

1. Run `gms-mcp-init --client <client> --scope <scope> --action check` to verify installation and active configuration.
2. Start a new client session so the client renegotiates the server protocol and capabilities.
3. Call `gm_capabilities` to inspect the active GMS-MCP tool profile. Optional UI, subscription, and Resolve behavior depends on the capabilities negotiated by that client session.

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

Runtime SDK v2 behavior is validated by:
- `cli/tests/python/test_mcp_protocol_compatibility.py`
- `cli/tests/python/test_mcp_stdio_transport_regression.py`
- `cli/tests/python/test_mcp_v2_http_transport.py`
- `cli/tests/python/test_mcp_v2_runtime.py`
- `cli/tests/python/test_mcp_v2_server_features.py`
- `cli/tests/python/test_mcp_v2_resolve.py`
- `cli/tests/python/test_mcp_v2_resolve_http.py`
- `cli/tests/python/test_mcp_v2_opentelemetry.py`

macOS CI includes parity install tests in addition to runner/session tests.
