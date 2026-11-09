"""
GameMaker Studio Event Helper
Library functions for managing object events. The ``gms event`` CLI and MCP
tools call these inside the project lock, write journal and validation.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .event_model import (
    build_event_entry,
    event_filename,
    event_filename_from_entry,
    event_matches,
    parse_event_filename,
    parse_event_spec,
    resolve_collision_object_reference,
)
from .exceptions import AssetNotFoundError, GMSError, ValidationError
from .path_safety import project_child_path, validate_resource_name
from .reference_scanner import read_gml_source
from .transactions import transactional_rename, transactional_unlink
from .utils import atomic_write_text, load_json_loose, save_json_loose

# ------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------


def _filename_to_event(filename: str) -> Tuple[Optional[int], Optional[int]]:
    """Convert GML event filename to event type and number."""
    try:
        spec = parse_event_filename(filename)
    except ValidationError:
        return None, None
    return spec.event_type, spec.event_num


def _event_to_filename(event_type: int, event_num: int, collision_object_id: Any = None) -> str:
    """Convert event type and number to GML filename."""
    return event_filename(event_type, event_num, collision_object_id)


def _object_dir(object_name: str, project_root: str | Path | None = None) -> tuple[str, Path]:
    """Return a validated object name and project-local object directory."""
    object_name = validate_resource_name(object_name, "object")
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    from .project_validation import resolve_asset_reference

    reference = resolve_asset_reference(root, object_name, "GMObject")
    return object_name, project_child_path(reference["path"], project_root=root, kind=f"object '{object_name}'").parent


# ------------------------------------------------------------------
# Library Functions
# ------------------------------------------------------------------


def list_events(object_name: str, project_root: str | Path | None = None) -> List[Dict[str, Any]]:
    """List all events for an object."""
    object_name, obj_dir = _object_dir(object_name, project_root)
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    events = []
    event_list = data.get("eventList", [])

    if not event_list:
        print(f"No events found for {object_name}")
        return []

    print(f"Events for {object_name}:")
    for event in event_list:
        e_type = event.get("eventType")
        e_num = event.get("eventNum")
        filename = event_filename_from_entry(event)
        print(f"  - {filename}")
        item: Dict[str, Any] = {"type": e_type, "num": e_num, "filename": filename}
        collision_reference = event.get("collisionObjectId")
        if isinstance(collision_reference, dict):
            item["collision_object"] = collision_reference.get("name")
        events.append(item)

    return events


def add_event(object_name: str, event_spec: str, template: str = "", project_root: str | Path | None = None) -> bool:
    """Add a new event to an object."""
    spec = parse_event_spec(event_spec)

    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    object_name, obj_dir = _object_dir(object_name, root)
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    collision_reference = None
    if spec.collision_object is not None:
        collision_reference = resolve_collision_object_reference(root, spec.collision_object)

    # Check if event already exists
    event_list = data.get("eventList", [])
    for event in event_list:
        if event_matches(event, spec):
            print(f"[WARN] Event {event_spec} already exists for {object_name}")
            return True

    # Create the GML file
    new_event = build_event_entry(spec, collision_reference, object_data=data)
    filename = event_filename_from_entry(new_event)
    gml_path = obj_dir / filename
    if gml_path.exists():
        # An orphaned file is adopted as the event's code. It never silently
        # replaces requested template content.
        if template and read_gml_source(gml_path) != template:
            raise ValidationError(
                f"{filename} already exists in {object_name} without an event entry and differs from the "
                "given template. Remove or edit that file, or add the event without a template to adopt it."
            )
        print(f"[OK] Adopted existing event file: {gml_path}")
    else:
        content = template if template else f"// {filename} event\n"
        atomic_write_text(gml_path, content)
        print(f"[OK] Created event file: {gml_path}")

    if "eventList" not in data:
        data["eventList"] = []
    data["eventList"].append(new_event)

    save_json_loose(obj_path, data)
    print(f"[OK] Added event {event_spec} to {object_name}")
    return True


def remove_event(
    object_name: str,
    event_spec: str,
    keep_file: bool = False,
    project_root: str | Path | None = None,
) -> bool:
    """Remove an event from an object."""
    spec = parse_event_spec(event_spec)

    object_name, obj_dir = _object_dir(object_name, project_root)
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    event_list = data.get("eventList", [])
    matching_events = [event for event in event_list if event_matches(event, spec)]
    new_event_list = [event for event in event_list if not event_matches(event, spec)]

    if len(new_event_list) == len(event_list):
        print(f"[WARN] Event {event_spec} not found for {object_name}")
        return False

    data["eventList"] = new_event_list
    save_json_loose(obj_path, data)

    filename = event_filename_from_entry(matching_events[0])
    gml_path = obj_dir / filename
    if gml_path.exists():
        if keep_file:
            # A file with an event filename but no event entry is an orphaned
            # event, which GameMaker and project validation reject. Keep the
            # code under a name that is not an event filename.
            kept_path = obj_dir / f"{gml_path.stem}.removed.gml"
            if kept_path.exists():
                raise ValidationError(f"Cannot keep removed event code; {kept_path.name} already exists")
            transactional_rename(gml_path, kept_path)
            print(f"[OK] Kept event code as: {kept_path}")
        else:
            transactional_unlink(gml_path)
            print(f"[OK] Deleted event file: {gml_path}")

    print(f"[OK] Removed event {event_spec} from {object_name}")
    return True


def duplicate_event(
    object_name: str,
    source_event_spec: str,
    target_event_spec: str,
    project_root: str | Path | None = None,
) -> bool:
    """
    Duplicate an event within an object.

    Example:
      duplicate_event("o_player", "step:0", "step:1") copies Step_0.gml to Step_1.gml.
      duplicate_event("o_player", "collision:o_enemy", "collision:o_wall") copies a collision event.
    """
    source_spec = parse_event_spec(source_event_spec)
    target_spec = parse_event_spec(target_event_spec)
    if target_spec.event_type != source_spec.event_type:
        raise ValidationError("Source and target events must have the same event type")

    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    object_name, obj_dir = _object_dir(object_name, root)
    obj_path = obj_dir / f"{object_name}.yy"
    if not obj_path.exists():
        raise AssetNotFoundError(f"Object '{object_name}' not found")

    data = load_json_loose(obj_path)
    if not data:
        raise GMSError(f"Failed to load object data for '{object_name}'")

    # Ensure source exists in eventList (or at least on disk)
    source_collision_reference = None
    if source_spec.collision_object is not None:
        source_collision_reference = resolve_collision_object_reference(root, source_spec.collision_object)
    target_collision_reference = None
    if target_spec.collision_object is not None:
        target_collision_reference = resolve_collision_object_reference(root, target_spec.collision_object)

    source_entry = build_event_entry(source_spec, source_collision_reference, object_data=data)
    target_entry = build_event_entry(target_spec, target_collision_reference, object_data=data)
    source_filename = event_filename_from_entry(source_entry)
    target_filename = event_filename_from_entry(target_entry)

    event_list = data.get("eventList", []) or []
    has_source_entry = any(event_matches(event, source_spec) for event in event_list)
    if not has_source_entry and not (obj_dir / source_filename).exists():
        raise ValidationError(f"Source event '{source_event_spec}' not found for {object_name}")

    # If target already exists, treat as success
    if any(event_matches(event, target_spec) for event in event_list):
        print(f"[WARN] Event {target_spec.canonical} already exists for {object_name}")
        return True

    # Copy or create the target GML file
    src_gml = obj_dir / source_filename
    dst_gml = obj_dir / target_filename
    source_code = read_gml_source(src_gml) if src_gml.exists() else f"// {target_filename} event\n"
    if dst_gml.exists():
        if src_gml.exists() and read_gml_source(dst_gml) != source_code:
            raise ValidationError(
                f"{target_filename} already exists in {object_name} without an event entry and differs from "
                f"{source_filename}. Remove or edit that file before duplicating."
            )
        print(f"[OK] Adopted existing event file: {dst_gml}")
    else:
        atomic_write_text(dst_gml, source_code)
        print(f"[OK] Created event file: {dst_gml}")

    if "eventList" not in data or data["eventList"] is None:
        data["eventList"] = []
    data["eventList"].append(target_entry)
    save_json_loose(obj_path, data)

    print(f"[OK] Duplicated event {source_event_spec} -> {target_event_spec} for {object_name}")
    return True
