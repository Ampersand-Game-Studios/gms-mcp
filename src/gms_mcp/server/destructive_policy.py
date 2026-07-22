from __future__ import annotations

from typing import Any, Dict


_DRY_RUN_GATED_WORKFLOWS = {
    "maintenance-dedupe-resources",
    "maintenance-prune-missing",
    "room-ops-delete",
}
_FIX_GATED_WORKFLOWS = {
    "maintenance-auto",
    "maintenance-lint",
    "maintenance-normalize-names",
    "maintenance-sync-events",
}
_DELETE_GATED_WORKFLOWS = {
    "maintenance-clean-old-files",
    "maintenance-clean-orphans",
}
_ALWAYS_DESTRUCTIVE_WORKFLOWS = {
    "event-fix",
    "event-remove",
    "maintenance-fix-issues",
    "room-instance-remove",
    "room-layer-remove",
    "room-ops-rename",
    "sprite-frames-remove",
    "workflow-rename",
    "workflow-swap-sprite",
}

_KNOWN_DESTRUCTIVE_WORKFLOWS = (
    *_DRY_RUN_GATED_WORKFLOWS,
    *_FIX_GATED_WORKFLOWS,
    *_DELETE_GATED_WORKFLOWS,
    *_ALWAYS_DESTRUCTIVE_WORKFLOWS,
)


def _read_bool_arg(args: Any, name: str, default: bool = False) -> bool:
    if isinstance(args, dict):
        return bool(args.get(name, default))
    return bool(getattr(args, name, default))


def _normalize_tool_name(tool_name: str | None) -> str:
    value = (tool_name or "").strip().lower().replace("_", "-")
    if value.startswith("gm-"):
        value = value[3:]
    return value


def _destructive_workflow_key(tool_name: str | None) -> str | None:
    normalized = _normalize_tool_name(tool_name)
    for workflow in _KNOWN_DESTRUCTIVE_WORKFLOWS:
        if normalized == workflow or normalized.startswith(f"{workflow}-"):
            return workflow
    return None


def is_real_destructive_cli_workflow(tool_name: str | None, args: Any) -> bool:
    workflow = _destructive_workflow_key(tool_name)
    if workflow is None:
        return False
    if workflow in _ALWAYS_DESTRUCTIVE_WORKFLOWS:
        return True
    if workflow in _DRY_RUN_GATED_WORKFLOWS:
        return not _read_bool_arg(args, "dry_run", default=False)
    if workflow in _FIX_GATED_WORKFLOWS:
        return _read_bool_arg(args, "fix", default=False)
    if workflow in _DELETE_GATED_WORKFLOWS:
        return _read_bool_arg(args, "delete", default=False)
    return False


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
