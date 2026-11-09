"""Shared flow helpers for GameMaker asset creation commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .auto_maintenance import handle_maintenance_failure, run_auto_maintenance, validate_asset_creation_safe
from .base_asset import preflight_asset_destination
from .utils import find_yyp, load_json, save_json, update_yyp_file, validate_name, validate_parent_path_for_project


def run_pre_creation_maintenance(args: Any, operation: str) -> Any:
    """Run the shared pre-creation maintenance gate."""
    if getattr(args, "skip_maintenance", False):
        return True
    print("[VALIDATE] Running pre-creation validation...")
    project_root = getattr(args, "project_root", ".")
    pre_result = run_auto_maintenance(project_root, fix_issues=False, verbose=False)
    if not validate_asset_creation_safe(pre_result):
        return handle_maintenance_failure(operation, pre_result)
    return True


def run_post_creation_maintenance(args: Any, operation: str) -> bool:
    """Run the shared post-creation maintenance gate."""
    if getattr(args, "skip_maintenance", False):
        return True
    print("[MAINT] Running post-creation maintenance...")
    post_result = run_auto_maintenance(
        getattr(args, "project_root", "."),
        fix_issues=False,
        verbose=getattr(args, "maintenance_verbose", True),
    )
    if not post_result.has_errors:
        print("[OK] Asset created and validated successfully!")
        return True
    return handle_maintenance_failure(operation, post_result)


def validate_named_asset(args: Any, asset_type: str, *, allow_constructor: bool = False) -> None:
    """Validate the standard asset name + parent path pair."""
    if allow_constructor:
        validate_name(args.name, asset_type, allow_constructor=True)
    else:
        validate_name(args.name, asset_type)
    validate_parent_path_for_project(getattr(args, "project_root", Path.cwd()), args.parent_path)


def preflight_asset_creation(args: Any, asset: Any, asset_type: str) -> dict[str, Any]:
    """Return read-only collision evidence for an asset-creation destination."""
    project_root = Path(getattr(args, "project_root", ".")).resolve()
    return preflight_asset_destination(
        project_root,
        asset_type=asset_type,
        folder_prefix=asset.folder_prefix,
        name=args.name,
        operation="create",
    )


def append_room_order_node(project_root: Path, room_name: str, room_path: str) -> bool:
    """Append a new room to RoomOrderNodes, as the GameMaker IDE does on room creation.

    Rooms missing from the room order are not part of the game's room sequence
    (``room_next``/``room_previous``), and a project whose order is empty has no
    startup room.
    """
    yyp_file = find_yyp(Path(project_root).resolve())
    project_data = load_json(yyp_file)
    room_order = project_data.setdefault("RoomOrderNodes", [])
    if not isinstance(room_order, list):
        print("[ERROR] Project RoomOrderNodes must be a list")
        return False
    normalized = room_path.replace("\\", "/").casefold()
    if any(
        isinstance(node, dict)
        and isinstance(node.get("roomId"), dict)
        and str(node["roomId"].get("path", "")).replace("\\", "/").casefold() == normalized
        for node in room_order
    ):
        return True
    room_order.append({"roomId": {"name": room_name, "path": room_path}})
    save_json(project_data, yyp_file)
    print(f"[OK] Added '{room_name}' to RoomOrderNodes")
    return True


def create_project_asset(
    args: Any,
    *,
    asset: Any,
    asset_type: str,
    label: str,
    kwargs: dict[str, Any] | None = None,
    success_message: str | None = None,
    success_lines: Iterable[str] | Callable[[Any], Iterable[str]] = (),
    allow_constructor: bool = False,
) -> bool:
    """Create files for a standard project asset and register it in the .yyp file."""
    initial_preflight = preflight_asset_creation(args, asset, asset_type)
    if not initial_preflight["available"] and initial_preflight.get("replacement_name_required"):
        print(
            f"[ERROR] Asset destination collision for '{args.name}'; "
            "provide a replacement name. Existing assets are never overwritten."
        )
        return False

    precheck = run_pre_creation_maintenance(args, f"{label} '{args.name}' creation")
    if precheck is not True:
        return precheck

    validate_named_asset(args, asset_type, allow_constructor=allow_constructor)

    # Maintenance can change the project, so revalidate immediately before the
    # first write. A stale resolution never permits an overwrite.
    final_preflight = preflight_asset_creation(args, asset, asset_type)
    if not final_preflight["available"]:
        print(
            f"[ERROR] Asset destination collision for '{args.name}'; "
            "provide a replacement name. Existing assets are never overwritten."
        )
        return False

    project_root = Path(getattr(args, "project_root", ".")).resolve()
    relative_path = asset.create_files(project_root, args.name, args.parent_path, **(kwargs or {}))
    resource_entry = {"id": {"name": args.name, "path": relative_path}}

    if not update_yyp_file(resource_entry, project_root=project_root):
        print(f"[ERROR] Failed to update .yyp file for {label.lower()} '{args.name}'")
        return False
    if asset_type == "room" and not append_room_order_node(project_root, args.name, relative_path):
        return False

    print(success_message or f"[OK] {label} '{args.name}' created successfully")
    lines = success_lines(args) if callable(success_lines) else success_lines
    for line in lines:
        print(line)

    return run_post_creation_maintenance(args, f"{label} '{args.name}' post-creation")
