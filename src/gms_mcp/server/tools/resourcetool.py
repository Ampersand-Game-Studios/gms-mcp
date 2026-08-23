"""MCP registration for isolated, explicitly configured ResourceTool checks."""

from __future__ import annotations

from typing import Any, Dict

from ...resourcetool_validation import validate_with_resourcetool
from ..mcp_types import Context
from ..project import ProjectAccessPolicy


def register(mcp: Any, ContextType: Any, *, project_access_policy: ProjectAccessPolicy) -> None:
    globals()["Context"] = ContextType

    @mcp.tool()
    def gm_resourcetool_validate(
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Validate the configured project through ResourceTool using a disposable copy."""
        _ = ctx
        approved_project = project_access_policy.authorize(".")
        return validate_with_resourcetool(approved_project)
