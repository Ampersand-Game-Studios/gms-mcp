from __future__ import annotations

import os
from typing import Any, Dict

from gms_helpers.operation_policy import canonical_operation_name, is_real_destructive_operation


def _env_flag(name: str, default: str = "0") -> bool:
    value = os.environ.get(name, default).strip().lower()
    return value in ("1", "true", "yes", "on")


def _requires_dry_run_for_destructive_tools() -> bool:
    return _env_flag("GMS_MCP_REQUIRE_DRY_RUN")


def _dry_run_policy_allowlist() -> set[str]:
    raw = os.environ.get("GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST", "")
    if not raw:
        return set()
    normalized = raw.replace(";", ",")
    allowlist: set[str] = set()
    for token in normalized.split(","):
        value = token.strip().lower()
        if value:
            allowlist.add(value)
    return allowlist


def _requires_dry_run_for_tool(tool_name: str) -> bool:
    if not _requires_dry_run_for_destructive_tools():
        return False
    return canonical_operation_name(tool_name) not in {
        canonical_operation_name(name) for name in _dry_run_policy_allowlist()
    }


def destructive_policy_preflight(tool_name: str, args: Any) -> Dict[str, Any] | None:
    """Gate actual destructive writes, including operations without preview flags."""
    if _requires_dry_run_for_tool(tool_name) and is_real_destructive_operation(tool_name, args):
        return _dry_run_policy_blocked_result(
            tool_name,
            "Use this operation's preview mode if supported, or explicitly allow this tool with "
            "GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST. Tools without a preview are blocked without an override.",
        )
    return None


def _dry_run_policy_blocked_result(tool_name: str, override_hint: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": (f"{tool_name} blocked by safety policy (GMS_MCP_REQUIRE_DRY_RUN=1)."),
        "blocked_by_policy": True,
        "policy": "require_dry_run",
        "hint": override_hint,
    }
