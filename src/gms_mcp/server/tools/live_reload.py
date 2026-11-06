"""Drive an external live-reload tool (for example GMS Fire) configured in ~/.gms-mcp/config.json."""

from __future__ import annotations

from typing import Any, Dict

from ..mcp_types import Context
from ..project import _resolve_project_directory


def _failure(tool: str, exc: Exception, project_root: str) -> Dict[str, Any]:
    from gms_helpers.project_config import project_live_reload_command_warnings

    try:
        warnings = project_live_reload_command_warnings(_resolve_project_directory(project_root))
    except Exception:
        warnings = []
    return {
        "ok": False,
        "tool": tool,
        "error": str(exc),
        "error_type": type(exc).__name__,
        "warnings": warnings,
    }


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    @mcp.tool()
    def gm_live_reload_status(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Report the state of the project's live-reload tool (e.g. GMS Fire).

        configured=false means ~/.gms-mcp/config.json has no "live_reload" section. gms-mcp itself does
        not hot-reload code; it only starts, stops and queries the tool the project names.
        """
        _ = ctx
        from gms_helpers import live_reload

        try:
            return live_reload.status(_resolve_project_directory(project_root))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_live_reload_status", exc, project_root)

    @mcp.tool()
    def gm_live_reload_start(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """Start the project's live-reload tool using the "live_reload.start" command from ~/.gms-mcp/config.json."""
        _ = ctx
        from gms_helpers import live_reload

        try:
            return live_reload.start(_resolve_project_directory(project_root))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_live_reload_start", exc, project_root)

    @mcp.tool()
    def gm_live_reload_stop(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """Stop the project's live-reload tool using the "live_reload.stop" command from ~/.gms-mcp/config.json."""
        _ = ctx
        from gms_helpers import live_reload

        try:
            return live_reload.stop(_resolve_project_directory(project_root))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_live_reload_stop", exc, project_root)
