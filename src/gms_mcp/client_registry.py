from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CLIENT_ACTIONS = ("setup", "check", "check-json", "app-setup")
CLIENT_SCOPES = ("workspace", "global")


@dataclass(frozen=True)
class ClientSpec:
    key: str
    aliases: tuple[str, ...]
    config_format: str
    workspace_supported: bool
    global_supported: bool
    workspace_relpath: str | None = None
    global_relpath: str | None = None
    description: str = ""

    def resolve_path(self, *, workspace_root: Path, scope: str, override: str | None) -> Path:
        if override:
            p = Path(override).expanduser()
            if p.is_absolute():
                return p
            return (workspace_root / p).resolve()

        if scope == "workspace":
            if not self.workspace_supported or not self.workspace_relpath:
                raise ValueError(f"Client '{self.key}' does not support workspace scope.")
            return workspace_root / self.workspace_relpath

        if not self.global_supported or not self.global_relpath:
            raise ValueError(f"Client '{self.key}' does not support global scope.")
        return Path.home() / self.global_relpath


CLIENT_SPECS: tuple[ClientSpec, ...] = (
    ClientSpec(
        key="cursor",
        aliases=(),
        config_format="json",
        workspace_supported=True,
        global_supported=True,
        workspace_relpath=".cursor/mcp.json",
        global_relpath=".cursor/mcp.json",
        description="Cursor MCP JSON config",
    ),
    ClientSpec(
        key="codex",
        aliases=(),
        config_format="toml",
        workspace_supported=True,
        global_supported=True,
        workspace_relpath=".codex/mcp.toml",
        global_relpath=".codex/config.toml",
        description="Codex MCP TOML config",
    ),
    ClientSpec(
        key="claude-code",
        aliases=("claude",),
        config_format="claude-mcp-json",
        workspace_supported=True,
        global_supported=False,
        workspace_relpath=".mcp.json",
        description="Claude Code CLI project-scoped .mcp.json",
    ),
    ClientSpec(
        key="claude-desktop",
        aliases=("claude-code-global",),
        config_format="claude-plugin-dir",
        workspace_supported=False,
        global_supported=True,
        global_relpath=".claude/plugins/gms-mcp",
        description="Claude Desktop global plugin bundle",
    ),
    ClientSpec(
        key="antigravity",
        aliases=("gemini",),
        config_format="json",
        workspace_supported=True,
        global_supported=True,
        workspace_relpath="mcp-configs/antigravity.mcp.json",
        global_relpath=".gemini/antigravity/mcp_config.json",
        description="Antigravity/Gemini MCP JSON config",
    ),
    ClientSpec(
        key="vscode",
        aliases=(),
        config_format="json",
        workspace_supported=True,
        global_supported=True,
        workspace_relpath="mcp-configs/vscode.mcp.json",
        global_relpath=".vscode/mcp.json",
        description="VSCode MCP JSON config",
    ),
    ClientSpec(
        key="windsurf",
        aliases=(),
        config_format="json",
        workspace_supported=True,
        global_supported=True,
        workspace_relpath="mcp-configs/windsurf.mcp.json",
        global_relpath=".codeium/windsurf/mcp.json",
        description="Windsurf MCP JSON config",
    ),
    ClientSpec(
        key="openclaw",
        aliases=(),
        config_format="json",
        workspace_supported=True,
        global_supported=True,
        workspace_relpath="mcp-configs/openclaw.mcp.json",
        global_relpath=".openclaw/mcp.json",
        description="OpenClaw MCP JSON config",
    ),
    ClientSpec(
        key="generic",
        aliases=(),
        config_format="json",
        workspace_supported=True,
        global_supported=True,
        workspace_relpath="mcp-configs/generic.mcp.json",
        global_relpath=".config/gms-mcp/generic.mcp.json",
        description="Generic MCP JSON config",
    ),
)


_SPEC_MAP: dict[str, ClientSpec] = {}
for _spec in CLIENT_SPECS:
    _SPEC_MAP[_spec.key] = _spec
    for _alias in _spec.aliases:
        _SPEC_MAP[_alias] = _spec


def resolve_client_spec(name: str) -> ClientSpec:
    if not name:
        raise ValueError("Client name is required.")
    key = name.strip().lower()
    spec = _SPEC_MAP.get(key)
    if spec is None:
        raise ValueError(f"Unsupported client '{name}'.")
    return spec


def canonical_client_names() -> tuple[str, ...]:
    return tuple(spec.key for spec in CLIENT_SPECS)


def all_client_names() -> tuple[str, ...]:
    return tuple(sorted(_SPEC_MAP.keys()))
