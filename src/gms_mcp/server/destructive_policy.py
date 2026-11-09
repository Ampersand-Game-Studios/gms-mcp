from __future__ import annotations

from typing import Any, Dict

from gms_helpers.operation_policy import is_real_destructive_operation


def is_real_destructive_cli_workflow(tool_name: str | None, args: Any) -> bool:
    """Real destructive writes must use the typed direct handler, never the CLI.

    The classification comes from ``gms_helpers.operation_policy`` so the MCP
    no-CLI set can never drift from the shared operation policy.
    """
    if not tool_name:
        return False
    return is_real_destructive_operation(tool_name, args)


def destructive_cli_blocked_result(tool_name: str, reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "direct_used": False,
        "stdout": "",
        "stderr": "",
        "exit_code": None,
        "error": "CLI execution is disabled for destructive MCP workflows.",
        "blocked_by_policy": True,
        "policy": "destructive_cli_disabled",
        "tool": tool_name,
        "reason": reason,
        "fallback_skipped": True,
        "fallback_skipped_reason": "destructive_cli_disabled",
        "execution_mode": "policy",
    }
