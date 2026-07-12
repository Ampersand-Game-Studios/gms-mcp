"""Canonical GameMaker event parsing and serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .exceptions import AssetNotFoundError, GMSError, ValidationError
from .path_safety import project_child_path, validate_resource_name
from .utils import find_yyp, load_json_loose


EVENT_TYPE_IDS = {
    "create": 0,
    "destroy": 1,
    "alarm": 2,
    "step": 3,
    "collision": 4,
    "keyboard": 5,
    "mouse": 6,
    "other": 7,
    "draw": 8,
    "keypress": 9,
    "keyrelease": 10,
    "trigger": 11,
    "cleanup": 12,
    "gesture": 13,
    "precreate": -1,
}

EVENT_TYPE_NAMES = {
    0: "Create",
    1: "Destroy",
    2: "Alarm",
    3: "Step",
    4: "Collision",
    5: "Keyboard",
    6: "Mouse",
    7: "Other",
    8: "Draw",
    9: "KeyPress",
    10: "KeyRelease",
    11: "Trigger",
    12: "CleanUp",
    13: "Gesture",
    -1: "PreCreate",
}

_EVENT_LABEL_TO_ID = {label.lower(): event_type for event_type, label in EVENT_TYPE_NAMES.items()}
_EVENT_ID_TO_SPEC = {event_type: type_name for type_name, event_type in EVENT_TYPE_IDS.items()}


@dataclass(frozen=True)
class EventSpec:
    """A validated event specification."""

    type_name: str
    event_type: int
    event_num: int = 0
    collision_object: str | None = None

    @property
    def canonical(self) -> str:
        if self.collision_object is not None:
            return f"collision:{self.collision_object}"
        return f"{self.type_name}:{self.event_num}"


def parse_event_spec(value: Any) -> EventSpec:
    """Parse CLI/MCP event syntax, including ``collision:<object_name>``."""
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        raise ValidationError("Event specification cannot be empty")

    parts = candidate.split(":")
    if len(parts) > 2:
        raise ValidationError(f"Invalid event specification: {candidate}")

    type_name = parts[0].strip().lower()
    if type_name not in EVENT_TYPE_IDS or type_name == "precreate":
        raise ValidationError(f"Unknown event type: {type_name}")

    suffix = parts[1].strip() if len(parts) == 2 else ""
    if type_name == "collision":
        if not suffix:
            raise ValidationError("Collision events require an object name, for example collision:o_wall")
        collision_object = validate_resource_name(suffix, "collision object")
        if collision_object.lstrip("-").isdigit():
            raise ValidationError("Collision events require an object name, not a numeric event subtype")
        return EventSpec(type_name, EVENT_TYPE_IDS[type_name], collision_object=collision_object)

    if not suffix:
        event_num = 0
    else:
        try:
            event_num = int(suffix)
        except ValueError as exc:
            raise ValidationError(f"Invalid event number in spec: {candidate}") from exc

    return EventSpec(type_name, EVENT_TYPE_IDS[type_name], event_num=event_num)


def parse_event_filename(filename: str) -> EventSpec:
    """Parse a GameMaker event filename into its canonical event model."""
    if not filename.endswith(".gml"):
        raise ValidationError(f"Invalid event filename: {filename}")

    stem = filename[:-4]
    if stem.startswith("Collision_"):
        collision_object = stem[len("Collision_") :]
        if not collision_object:
            raise ValidationError(f"Invalid collision event filename: {filename}")
        return parse_event_spec(f"collision:{collision_object}")

    if "_" not in stem:
        raise ValidationError(f"Invalid event filename: {filename}")
    type_label, number = stem.rsplit("_", 1)
    event_type = _EVENT_LABEL_TO_ID.get(type_label.lower())
    if event_type is None:
        raise ValidationError(f"Unknown event filename type: {filename}")
    try:
        event_num = int(number)
    except ValueError as exc:
        raise ValidationError(f"Invalid event filename number: {filename}") from exc
    return EventSpec(_EVENT_ID_TO_SPEC[event_type], event_type, event_num=event_num)


def collision_object_name(reference: Any) -> str | None:
    """Return the object name from a modern GameMaker object reference."""
    if not isinstance(reference, Mapping):
        return None
    name = reference.get("name")
    return name if isinstance(name, str) and name else None


def event_filename(event_type: int, event_num: int, collision_object_id: Any = None) -> str:
    """Return the GameMaker filename for an event entry."""
    type_label = EVENT_TYPE_NAMES.get(event_type)
    if type_label is None:
        raise ValidationError(f"Unknown event type id: {event_type}")
    if event_type == EVENT_TYPE_IDS["collision"]:
        object_name = collision_object_name(collision_object_id)
        if object_name is None:
            raise ValidationError("Collision event is missing a valid collisionObjectId reference")
        return f"Collision_{object_name}.gml"
    return f"{type_label}_{event_num}.gml"


def event_filename_from_entry(event: Mapping[str, Any]) -> str:
    """Return the expected filename for a serialized GMEvent entry."""
    return event_filename(
        int(event.get("eventType", 0)),
        int(event.get("eventNum", 0)),
        event.get("collisionObjectId"),
    )


def event_matches(event: Mapping[str, Any], spec: EventSpec) -> bool:
    """Return whether a serialized event entry represents ``spec``."""
    if event.get("eventType") != spec.event_type:
        return False
    if spec.collision_object is not None:
        return collision_object_name(event.get("collisionObjectId")) == spec.collision_object
    return event.get("eventNum") == spec.event_num


def rewrite_collision_event_target(event: dict[str, Any], old_name: str, new_name: str) -> bool:
    """Rewrite one exact collision target reference and its canonical event identity."""
    if event.get("eventType") != EVENT_TYPE_IDS["collision"]:
        return False
    reference = event.get("collisionObjectId")
    if not isinstance(reference, Mapping):
        return False

    old_path = f"objects/{old_name}/{old_name}.yy"
    name_matches = reference.get("name") == old_name
    path_matches = str(reference.get("path") or "").replace("\\", "/") == old_path
    if not name_matches and not path_matches:
        return False
    if not name_matches or not path_matches:
        raise ValidationError(f"Collision event has a partial/corrupt reference to '{old_name}'")
    if event.get("eventNum") != 0:
        raise ValidationError(f"Collision event for '{old_name}' must use eventNum 0")

    old_identity = f"Collision_{old_name}"
    if event.get("%Name") != old_identity or event.get("name") != old_identity:
        raise ValidationError(f"Collision event identity does not match target '{old_name}'")

    new_identity = f"Collision_{new_name}"
    event["%Name"] = new_identity
    event["name"] = new_identity
    event["collisionObjectId"] = {
        "name": new_name,
        "path": f"objects/{new_name}/{new_name}.yy",
    }
    return True


def build_event_entry(spec: EventSpec, collision_reference: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build a modern GMEvent entry from a parsed specification."""
    if spec.collision_object is not None:
        if collision_reference is None or collision_object_name(collision_reference) != spec.collision_object:
            raise ValidationError(f"Collision event target '{spec.collision_object}' is not resolved")
        collision_object_id: Mapping[str, str] | None = dict(collision_reference)
    else:
        collision_object_id = None

    filename = event_filename(spec.event_type, spec.event_num, collision_object_id)
    event_name = filename.removesuffix(".gml")
    return {
        "$GMEvent": "v1",
        "%Name": event_name,
        "collisionObjectId": collision_object_id,
        "eventNum": spec.event_num,
        "eventType": spec.event_type,
        "isDnD": False,
        "name": event_name,
        "resourceType": "GMEvent",
        "resourceVersion": "2.0",
    }


def resolve_collision_object_reference(project_root: str | Path, object_name: str) -> dict[str, str]:
    """Resolve an existing project object to a GameMaker object reference."""
    root = Path(project_root).resolve()
    object_name = validate_resource_name(object_name, "collision object")
    yyp_path = find_yyp(root)
    project_data = load_json_loose(yyp_path)
    if not isinstance(project_data, dict):
        raise GMSError(f"Failed to load GameMaker project: {yyp_path}")

    resource_path: str | None = None
    for resource in project_data.get("resources", []) or []:
        resource_id = resource.get("id") if isinstance(resource, dict) else None
        if not isinstance(resource_id, dict) or resource_id.get("name") != object_name:
            continue
        candidate = resource_id.get("path")
        if isinstance(candidate, str) and candidate.replace("\\", "/").startswith("objects/"):
            resource_path = candidate.replace("\\", "/")
            break

    if resource_path is None:
        raise AssetNotFoundError(f"Collision target object '{object_name}' is not registered in the project")

    parts = Path(resource_path).parts
    if len(parts) != 3 or parts[0] != "objects" or not resource_path.endswith(".yy"):
        raise ValidationError(f"Collision target object '{object_name}' has an invalid project path: {resource_path}")
    object_path = project_child_path(*parts, project_root=root, kind=f"collision object '{object_name}'")
    if not object_path.is_file():
        raise AssetNotFoundError(
            f"Collision target object '{object_name}' points to a missing asset file: {resource_path}"
        )

    object_data = load_json_loose(object_path)
    if not isinstance(object_data, dict) or object_data.get("resourceType") != "GMObject":
        raise ValidationError(f"Collision target '{object_name}' is not a valid GameMaker object asset")

    return {"name": object_name, "path": resource_path}
