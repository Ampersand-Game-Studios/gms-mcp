from __future__ import annotations

from typing import Any, Dict

from ..mcp_types import Context
from ..project import _resolve_project_directory_no_deps


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Runtime management tools
    # -----------------------------
    @mcp.tool()
    async def gm_runtime_list(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        List all installed GameMaker runtimes.
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        installed = manager.list_installed()
        pinned = manager.get_pinned()
        active = manager.select()
        
        return {
            "runtimes": [r.to_dict() for r in installed],
            "pinned_version": pinned,
            "active_version": active.version if active else None,
            "count": len(installed)
        }

    @mcp.tool()
    async def gm_runtime_pin(
        version: str,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Pin a specific runtime version for this project.
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        success = manager.pin(version)
        
        return {
            "ok": success,
            "pinned_version": version if success else None,
            "error": None if success else f"Runtime version {version} is not installed or invalid."
        }

    @mcp.tool()
    async def gm_runtime_unpin(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Remove runtime pin, reverting to auto-select (newest).
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        success = manager.unpin()
        
        return {
            "ok": True,  # Always true even if no pin existed
            "message": "Runtime pin removed." if success else "No runtime pin existed."
        }

    @mcp.tool()
    async def gm_runtime_verify(
        version: str | None = None,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Verify a runtime is valid and ready to use.
        If version is None, verifies the currently selected runtime.
        """
        from gms_helpers.runtime_manager import RuntimeManager
        from pathlib import Path
        
        project_directory = _resolve_project_directory_no_deps(project_root)
        manager = RuntimeManager(project_directory)
        
        return manager.verify(version)
