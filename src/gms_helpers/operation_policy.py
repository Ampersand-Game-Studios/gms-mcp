"""Shared operation classification, boundary checks and result semantics.

CLI and MCP use the same canonical names. Imported images/templates are inputs,
not project destinations, and intentionally may live outside the project.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .path_safety import assert_project_tree_contained, project_relative_path, validate_resource_name


ASSET_TYPES = frozenset(
    "script object sprite room folder font shader animcurve sound path tileset timeline sequence note".split()
)
PROJECT_MUTATIONS = frozenset(
    {
        *(f"create-{kind}" for kind in ASSET_TYPES),
        "asset-delete",
        "safe-delete",
        "workflow-duplicate",
        "workflow-rename",
        "workflow-swap-sprite",
        "event-add",
        "event-remove",
        "event-duplicate",
        "event-fix",
        "sprite-add-frame",
        "sprite-remove-frame",
        "sprite-duplicate-frame",
        "sprite-import-strip",
        "room-ops-duplicate",
        "room-ops-rename",
        "room-ops-delete",
        "room-layer-add",
        "room-layer-remove",
        "room-instance-add",
        "room-instance-remove",
        "texture-group-create",
        "texture-group-update",
        "texture-group-rename",
        "texture-group-delete",
        "texture-group-assign",
        "maintenance-auto",
        "maintenance-lint",
        "maintenance-prune-missing",
        "maintenance-dedupe-resources",
        "maintenance-sync-events",
        "maintenance-normalize-names",
        "maintenance-clean-old-files",
        "maintenance-clean-orphans",
        "maintenance-fix-issues",
        "bridge-install",
        "bridge-uninstall",
        "bridge-enable-one-shot",
        "runtime-pin",
        "runtime-unpin",
        "yyp-register",
        "yyp-unregister",
        "yyp-normalize-order",
        "asset-move",
        "included-file-add",
        "included-file-remove",
        "config-add",
        "audio-group-create",
        "game-bridge-install",
    }
)
_FIX_OPERATIONS = frozenset(
    {"maintenance-auto", "maintenance-lint", "maintenance-sync-events", "maintenance-normalize-names"}
)
_DELETE_OPERATIONS = frozenset({"maintenance-clean-old-files", "maintenance-clean-orphans"})
_DESTRUCTIVE_STATE_OPERATIONS = frozenset({"doc-cache-clear", "run-stop", "run-command"})
_ADDITIVE_OPERATIONS = frozenset(
    {
        *(f"create-{kind}" for kind in ASSET_TYPES),
        "workflow-duplicate",
        "room-ops-duplicate",
        "sprite-import-strip",
        "texture-group-create",
        "yyp-register",
        "included-file-add",
        "config-add",
        "audio-group-create",
    }
)

# These operations do not edit GameMaker resources. Keep their real side effects
# explicit rather than pretending every operation outside PROJECT_MUTATIONS reads.
_OPERATION_SCOPES = {
    **dict.fromkeys(
        "doc-lookup doc-search doc-list doc-categories doc-cache-clear build-index".split(),
        "cache",
    ),
    **dict.fromkeys("find-definition find-references list-symbols".split(), "read"),
    **dict.fromkeys("help version".split(), "read"),
    **dict.fromkeys("compile run run-stop run-command verification-flush resourcetool-validate".split(), "runtime"),
    # Snapshot builds and live sessions run Igor and the game on throwaway copies; they
    # never edit project resources.
    **dict.fromkeys(
        "snapshot-compile test-run game-start game-stop game-command game-screenshot live-reload-start live-reload-stop".split(),
        "runtime",
    ),
    # Stages (and optionally commits) in git; the working tree's project files are untouched.
    "vcs-stage": "vcs",
    **dict.fromkeys(
        "project-check included-file-list config-list audio-group-list lock-status run-log game-status game-log live-reload-status".split(),
        "read",
    ),
    **dict.fromkeys(
        "skills-install skills-uninstall telemetry-enable telemetry-disable telemetry-flush telemetry-clear".split(),
        "local-config",
    ),
    **dict.fromkeys(
        "capabilities project-info project-dashboard mcp-health diagnostics check-updates list-assets read-asset search-references get-asset-graph get-project-stats event-list event-validate room-ops-list room-layer-list room-instance-list sprite-frame-count sprite-frames-count texture-group-list texture-group-read texture-group-members texture-group-scan maintenance-validate-json maintenance-list-orphans maintenance-validate-paths maintenance-health bridge-status run-logs run-status runtime-list runtime-verify verification-status doc-cache-stats skills-list telemetry-status".split(),
        "read",
    ),
}


def operation_scope(tool_name: str) -> str:
    """Return the explicit state scope of each exposed CLI/MCP operation."""
    name = canonical_operation_name(tool_name)
    if name in PROJECT_MUTATIONS:
        return "project"
    return _OPERATION_SCOPES.get(name, "unknown")


def is_write_free_operation(tool_name: str, args: Any) -> bool:
    """Readers and honest project previews must not persist execution side effects."""
    scope = operation_scope(tool_name)
    return scope == "read" or (scope == "project" and not is_project_mutation(tool_name, args))


def canonical_operation_name(tool_name: str) -> str:
    name = tool_name.lower().replace("_", "-").replace(".", "-")
    if name.startswith("gm-"):
        name = name[3:]
    if name.startswith("asset-create-"):
        name = name.removeprefix("asset-")
    if name.startswith("asset-delete-"):
        name = "asset-delete"
    return {
        "workflow-safe-delete": "safe-delete",
        "texture-groups-show": "texture-group-read",
        "runner-compile": "compile",
        "runner-run": "run",
        "runner-stop": "run-stop",
        "runner-status": "run-status",
        "run-compile": "compile",
        "run-run": "run",
        "run-start": "run",
        "symbol-build": "build-index",
        "symbol-find-definition": "find-definition",
        "symbol-find-references": "find-references",
        "symbol-list": "list-symbols",
        "sprite-frames-add": "sprite-add-frame",
        "sprite-frames-remove": "sprite-remove-frame",
        "sprite-frames-duplicate": "sprite-duplicate-frame",
        "sprite-frames-import-strip": "sprite-import-strip",
    }.get(name, name.replace("texture-groups-", "texture-group-"))


def _arguments(args: Any) -> Mapping[str, Any]:
    return args if isinstance(args, Mapping) else vars(args)


def is_project_mutation(tool_name: str, args: Any) -> bool:
    name = canonical_operation_name(tool_name)
    values = _arguments(args)
    if name not in PROJECT_MUTATIONS or values.get("dry_run") is True:
        return False
    if name in _FIX_OPERATIONS:
        return values.get("fix") is True
    if name in _DELETE_OPERATIONS:
        return values.get("delete") is True
    if name == "safe-delete" and "apply" in values:
        return values["apply"] is True
    return True


def is_real_destructive_operation(tool_name: str, args: Any) -> bool:
    """Existing-resource edits and removals require the destructive write policy."""
    if canonical_operation_name(tool_name) in _DESTRUCTIVE_STATE_OPERATIONS:
        return True  # No honest preview exists for these cache/runtime actions.
    return is_project_mutation(tool_name, args) and canonical_operation_name(tool_name) not in _ADDITIVE_OPERATIONS


def validate_project_operation(project_root: str | Path, args: Any) -> Path:
    """Preflight all project links and destination/resource arguments before writes."""
    root = assert_project_tree_contained(Path(project_root))
    values = _arguments(args)
    for field in ("asset_path", "sprite_path", "parent_path", "path", "folder_path"):
        if values.get(field):
            project_relative_path(values[field], project_root=root, kind=field)
    for field in (
        "name",
        "new_name",
        "object",
        "object_name",
        "room_name",
        "source_room",
        "asset_name",
        "sprite_name",
        "parent_object",
        "sprite_id",
    ):
        if values.get(field):
            validate_resource_name(values[field], field)
    # Texture-group explicit asset selections may contain relative YY paths.
    assets = values.get("assets")
    if isinstance(assets, str):
        assets = assets.split(",")
    if isinstance(assets, (list, tuple)):
        for asset in assets:
            if asset:
                project_relative_path(asset, project_root=root, kind="asset selection")
    return root


def operation_succeeded(result: Any) -> bool:
    """Never interpret a truthy typed failure/report object as success."""
    if isinstance(result, Mapping):
        if result.get("error") or result.get("errors") or result.get("has_errors") or result.get("blocked_by_policy"):
            return False
        if str(result.get("status", "")).lower() in {"error", "failed", "failure", "cancelled", "canceled", "blocked"}:
            return False
        if any(result.get(key) is False for key in ("ok", "success")):
            return False
        return bool(result.get("ok", result.get("success", True)))
    if getattr(result, "has_errors", False):
        return False
    for field in ("success", "ok"):
        value = getattr(result, field, None)
        if isinstance(value, bool):
            return value
    return bool(result)
