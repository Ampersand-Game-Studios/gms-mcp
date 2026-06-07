"""Post-mutation compile verification policy and deferred batch state."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from gms_helpers.transactions import compile_verify_project
from gms_helpers.utils import atomic_write_text, load_json_loose


_TRUE_VALUES = {"1", "true", "yes", "on"}
_ALWAYS_VERIFY_VALUES = {*_TRUE_VALUES, "always", "compile", "ide"}
_SMART_VERIFY_VALUES = {"smart", "risk", "risky", "batch", "batched"}
_OFF_VALUES = {"", "0", "false", "no", "off", "none"}

_HIGH_RISK_TOOL_NAMES = {
    "gm_asset_delete",
    "gm_bridge_install",
    "gm_bridge_uninstall",
    "gm_bridge_enable_one_shot",
    "gm_maintenance_clean_old_files",
    "gm_maintenance_clean_orphans",
    "gm_maintenance_dedupe_resources",
    "gm_maintenance_fix_issues",
    "gm_maintenance_normalize_names",
    "gm_maintenance_prune_missing",
    "gm_maintenance_sync_events",
    "gm_room_ops_delete",
    "gm_room_ops_duplicate",
    "gm_room_ops_rename",
    "gm_safe_delete",
    "gm_texture_group_create",
    "gm_texture_group_delete",
    "gm_texture_group_rename",
    "gm_workflow_delete",
    "gm_workflow_duplicate",
    "gm_workflow_rename",
}
_HIGH_RISK_TOOL_PREFIXES = (
    "gm_create_",
    "gm_room_instance_",
    "gm_room_layer_",
)
_BATCHABLE_TOOL_NAMES = {
    "gm_event_add",
    "gm_event_duplicate",
    "gm_event_fix",
    "gm_event_remove",
    "gm_sprite_add_frame",
    "gm_sprite_duplicate_frame",
    "gm_sprite_import_strip",
    "gm_sprite_remove_frame",
    "gm_texture_group_assign",
    "gm_texture_group_update",
    "gm_workflow_swap_sprite",
}


@dataclass
class MutationVerificationDecision:
    mode: str
    action: str
    risk: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def current_verification_mode() -> str:
    """Return off, always, smart, or unknown for the active post-mutation policy."""
    if _env_truthy("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION"):
        return "always"
    raw_value = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY")
    if raw_value is None:
        return "smart"
    raw = raw_value.strip().lower()
    if raw in _ALWAYS_VERIFY_VALUES:
        return "always"
    if raw in _SMART_VERIFY_VALUES:
        return "smart"
    if raw in _OFF_VALUES:
        return "off"
    return "unknown"


def _matches_prefix(tool_name: str, prefixes: Iterable[str]) -> bool:
    return any(tool_name.startswith(prefix) for prefix in prefixes)


def _classify_risk(tool_name: str) -> tuple[str, str]:
    if tool_name in _BATCHABLE_TOOL_NAMES:
        return "batchable", "safe to defer until a related mutation batch is complete"
    if tool_name in _HIGH_RISK_TOOL_NAMES or _matches_prefix(tool_name, _HIGH_RISK_TOOL_PREFIXES):
        return "high", "structural GameMaker project mutation"
    return "unknown", "unclassified transactional mutation"


def decide_mutation_verification(tool_name: str) -> MutationVerificationDecision:
    mode = current_verification_mode()
    risk, reason = _classify_risk(tool_name)

    if mode == "always":
        return MutationVerificationDecision(mode=mode, action="compile", risk=risk, reason="compile mode is enabled")
    if mode == "smart":
        if risk == "batchable":
            return MutationVerificationDecision(mode=mode, action="defer", risk=risk, reason=reason)
        return MutationVerificationDecision(mode=mode, action="compile", risk=risk, reason=reason)
    return MutationVerificationDecision(mode=mode, action="skip", risk=risk, reason="post-mutation compile verification is off")


def _state_path(project_root: Path) -> Path:
    return project_root / ".gms_mcp" / "verification_state.json"


def _load_state(project_root: Path) -> Dict[str, Any]:
    path = _state_path(project_root)
    data = load_json_loose(path) if path.exists() else None
    return data if isinstance(data, dict) else {"version": 1}


def _write_state(project_root: Path, state: Dict[str, Any]) -> None:
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(state, indent=2, sort_keys=True) + "\n")


def get_pending_compile_verification(project_root: str | Path) -> Dict[str, Any] | None:
    root = Path(project_root).resolve()
    pending = _load_state(root).get("pending_compile_verification")
    if isinstance(pending, dict) and pending.get("required"):
        return pending
    return None


def mark_compile_verification_pending(
    project_root: str | Path,
    *,
    tool_name: str,
    decision: MutationVerificationDecision,
    transaction: Dict[str, Any],
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    state = _load_state(root)
    pending = state.get("pending_compile_verification")
    if not isinstance(pending, dict) or not pending.get("required"):
        pending = {
            "required": True,
            "first_pending_at": _now_iso(),
            "operations": [],
        }

    operations = pending.get("operations")
    if not isinstance(operations, list):
        operations = []
        pending["operations"] = operations

    changes = transaction.get("changes") if isinstance(transaction.get("changes"), dict) else {}
    operations.append(
        {
            "tool": tool_name,
            "risk": decision.risk,
            "reason": decision.reason,
            "recorded_at": _now_iso(),
            "changed_count": int(changes.get("changed_count", 0)) if isinstance(changes, dict) else 0,
        }
    )
    pending["last_pending_at"] = _now_iso()
    pending["operation_count"] = len(operations)
    pending["tools"] = sorted({str(item.get("tool")) for item in operations if isinstance(item, dict)})
    state["pending_compile_verification"] = pending
    _write_state(root, state)
    return pending


def clear_pending_compile_verification(project_root: str | Path) -> Dict[str, Any] | None:
    root = Path(project_root).resolve()
    state = _load_state(root)
    pending = state.pop("pending_compile_verification", None)
    _write_state(root, state)
    return pending if isinstance(pending, dict) and pending.get("required") else None


def flush_pending_compile_verification(
    project_root: str | Path,
    *,
    force: bool = False,
    platform: str | None = None,
    runtime: str | None = None,
    timeout_seconds: int | None = None,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    pending = get_pending_compile_verification(root)
    if pending is None and not force:
        return {
            "ok": True,
            "compiled": False,
            "mode": current_verification_mode(),
            "pending_compile_verification": None,
            "message": "No pending compile verification.",
        }

    verification = compile_verify_project(
        root,
        platform=platform,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
    )
    if verification.get("ok"):
        cleared = clear_pending_compile_verification(root)
        return {
            "ok": True,
            "compiled": True,
            "mode": current_verification_mode(),
            "compile_verification": verification,
            "cleared_pending_compile_verification": cleared,
            "pending_compile_verification": None,
        }

    return {
        "ok": False,
        "compiled": True,
        "mode": current_verification_mode(),
        "error": "Compile verification failed; pending marker kept.",
        "compile_verification": verification,
        "pending_compile_verification": pending,
    }
