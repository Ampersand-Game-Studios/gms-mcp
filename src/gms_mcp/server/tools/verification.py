from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..mcp_types import Context
from ..verification_policy import (
    current_verification_mode,
    flush_pending_compile_verification,
    get_pending_compile_verification,
)


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    @mcp.tool()
    def gm_verification_status(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """Show pending post-mutation compile verification state for the project."""
        _ = ctx
        root = Path(project_root).resolve()
        return {
            "ok": True,
            "mode": current_verification_mode(),
            "project_root": str(root),
            "pending_compile_verification": get_pending_compile_verification(root),
        }

    @mcp.tool()
    def gm_verification_flush(
        project_root: str = ".",
        force: bool = False,
        platform: str = "",
        runtime: str = "",
        timeout_seconds: int = 0,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Compile once to verify pending smart-mode mutations."""
        _ = ctx
        return flush_pending_compile_verification(
            project_root,
            force=force,
            platform=platform or None,
            runtime=runtime or None,
            timeout_seconds=timeout_seconds if timeout_seconds > 0 else None,
        )
