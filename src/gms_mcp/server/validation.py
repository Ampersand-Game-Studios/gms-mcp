"""MCP boundary validation for GameMaker tools."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, List, Mapping

from gms_helpers.exceptions import ValidationError
from gms_helpers.path_safety import project_child_path


ValidationErrorList = List[Dict[str, str]]


_RESOURCE_NAME_PARAMS = {
    "object",
    "object_name",
    "room_name",
    "source_room",
    "new_name",
    "old_name",
    "parent_object",
    "instance_id",
    "group_name",
    "symbol_name",
}
_NAME_TOOLS_PREFIXES = (
    "gm_create_",
    "gm_texture_group_",
)
_ASSET_TYPES = frozenset(
    {
        "animcurve",
        "font",
        "folder",
        "note",
        "object",
        "path",
        "room",
        "script",
        "sequence",
        "shader",
        "sound",
        "sprite",
        "tileset",
        "timeline",
    }
)
_ASSET_PATH_TYPES = {
    "animcurves": "animcurve",
    "fonts": "font",
    "notes": "note",
    "objects": "object",
    "paths": "path",
    "rooms": "room",
    "scripts": "script",
    "sequences": "sequence",
    "shaders": "shader",
    "sounds": "sound",
    "sprites": "sprite",
    "tilesets": "tileset",
    "timelines": "timeline",
}
_LAYER_TYPES = frozenset({"background", "instance", "instances", "asset", "tile", "path", "effect"})
_OUTPUT_MODES = frozenset({"full", "tail", "none"})
_DIAGNOSTIC_DEPTHS = frozenset({"quick", "deep"})
_REFERENCE_SCOPES = frozenset({"all", "gml", "yy", "scripts", "objects", "extensions", "datafiles"})
_RUNTIMES = frozenset({"VM", "YYC", "vm", "yyc"})
_PLATFORMS = frozenset({"Windows", "macOS", "Linux", "HTML5", "Android", "iOS", "GX.games"})
_ANIMCURVE_TYPES = frozenset({"linear", "smooth", "ease_in", "ease_out"})
_PATH_TYPES = frozenset({"straight", "smooth", "circle"})
_SPRITE_STRIP_LAYOUTS = frozenset({"horizontal", "vertical", "grid"})
_BOOLEAN_FIELDS = frozenset(
    {
        "auto",
        "background",
        "bold",
        "closed",
        "delete",
        "dry_run",
        "fix",
        "force",
        "include_assets",
        "include_info",
        "include_top_level",
        "is_constructor",
        "italic",
        "keep_file",
        "maintenance_verbose",
        "no_auto_fix",
        "quiet",
        "safe_mode",
        "skip_maintenance",
        "strict_disk_check",
        "update_existing_configs",
        "update_references",
        "uses_sdf",
        "verbose",
        "yes",
    }
)


@dataclass(frozen=True)
class OperationModel:
    """Typed schema/domain model for an MCP operation."""

    writes: bool
    required: frozenset[str] = frozenset()
    resource_names: frozenset[str] = frozenset()
    group_names: frozenset[str] = frozenset()
    asset_names: Mapping[str, str] = field(default_factory=dict)
    dynamic_asset_names: Mapping[str, str] = field(default_factory=dict)
    inferred_asset_names: Mapping[str, str] = field(default_factory=dict)
    parent_paths: frozenset[str] = frozenset()
    folder_paths: frozenset[str] = frozenset()
    asset_paths: Mapping[str, str | None] = field(default_factory=dict)
    png_paths: frozenset[str] = frozenset()
    event_specs: frozenset[str] = frozenset()
    choices: Mapping[str, frozenset[Any]] = field(default_factory=dict)
    int_ranges: Mapping[str, tuple[int | None, int | None]] = field(default_factory=dict)
    float_ranges: Mapping[str, tuple[float | None, float | None]] = field(default_factory=dict)
    string_lists: Mapping[str, frozenset[str] | None] = field(default_factory=dict)
    object_maps: frozenset[str] = frozenset()
    non_empty_strings: frozenset[str] = frozenset()


def _model(
    *,
    writes: bool = False,
    required: Iterable[str] = (),
    resource_names: Iterable[str] = (),
    group_names: Iterable[str] = (),
    asset_names: Mapping[str, str] | None = None,
    dynamic_asset_names: Mapping[str, str] | None = None,
    inferred_asset_names: Mapping[str, str] | None = None,
    parent_paths: Iterable[str] = (),
    folder_paths: Iterable[str] = (),
    asset_paths: Mapping[str, str | None] | None = None,
    png_paths: Iterable[str] = (),
    event_specs: Iterable[str] = (),
    choices: Mapping[str, Iterable[Any]] | None = None,
    int_ranges: Mapping[str, tuple[int | None, int | None]] | None = None,
    float_ranges: Mapping[str, tuple[float | None, float | None]] | None = None,
    string_lists: Mapping[str, Iterable[str] | None] | None = None,
    object_maps: Iterable[str] = (),
    non_empty_strings: Iterable[str] = (),
) -> OperationModel:
    return OperationModel(
        writes=writes,
        required=frozenset(required),
        resource_names=frozenset(resource_names),
        group_names=frozenset(group_names),
        asset_names=dict(asset_names or {}),
        dynamic_asset_names=dict(dynamic_asset_names or {}),
        inferred_asset_names=dict(inferred_asset_names or {}),
        parent_paths=frozenset(parent_paths),
        folder_paths=frozenset(folder_paths),
        asset_paths=dict(asset_paths or {}),
        png_paths=frozenset(png_paths),
        event_specs=frozenset(event_specs),
        choices={field_name: frozenset(values) for field_name, values in (choices or {}).items()},
        int_ranges=dict(int_ranges or {}),
        float_ranges=dict(float_ranges or {}),
        string_lists={
            field_name: (None if values is None else frozenset(values))
            for field_name, values in (string_lists or {}).items()
        },
        object_maps=frozenset(object_maps),
        non_empty_strings=frozenset(non_empty_strings),
    )


def _create_model(
    asset_type: str,
    *,
    extra_required: Iterable[str] = (),
    resource_names: Iterable[str] = (),
    asset_names: Mapping[str, str] | None = None,
    choices: Mapping[str, Iterable[Any]] | None = None,
    int_ranges: Mapping[str, tuple[int | None, int | None]] | None = None,
    float_ranges: Mapping[str, tuple[float | None, float | None]] | None = None,
    non_empty_strings: Iterable[str] = (),
) -> OperationModel:
    model_asset_names = {"name": asset_type}
    model_asset_names.update(asset_names or {})
    return _model(
        writes=True,
        required=("name", *extra_required),
        resource_names=resource_names,
        asset_names=model_asset_names,
        parent_paths=("parent_path",),
        choices=choices,
        int_ranges=int_ranges,
        float_ranges=float_ranges,
        non_empty_strings=non_empty_strings,
    )


_OPERATION_MODELS: dict[str, OperationModel] = {
    "gm_create_script": _create_model("script"),
    "gm_create_object": _create_model(
        "object",
        resource_names=("sprite_id", "parent_object"),
        asset_names={"name": "object", "sprite_id": "sprite", "parent_object": "object"},
    ),
    "gm_create_sprite": _create_model("sprite", int_ranges={"frame_count": (1, None)}),
    "gm_create_room": _create_model("room", int_ranges={"width": (1, None), "height": (1, None)}),
    "gm_create_folder": _model(
        writes=True,
        required=frozenset({"name", "path"}),
        asset_names={"name": "folder"},
        folder_paths=("path",),
    ),
    "gm_create_font": _create_model(
        "font",
        non_empty_strings=("font_name",),
        choices={"aa_level": (0, 1, 2, 3)},
        int_ranges={"size": (1, None)},
    ),
    "gm_create_shader": _create_model("shader", choices={"shader_type": (1, 2, 3, 4)}),
    "gm_create_animcurve": _create_model(
        "animcurve",
        choices={"curve_type": _ANIMCURVE_TYPES},
        non_empty_strings=("channel_name",),
    ),
    "gm_create_sound": _create_model(
        "sound",
        choices={"sound_type": (0, 1, 2), "format": (0, 1, 2)},
        int_ranges={"bitrate": (1, None), "sample_rate": (1, None)},
        float_ranges={"volume": (0.0, 1.0), "pitch": (0.0, None)},
    ),
    "gm_create_path": _create_model(
        "path",
        choices={"path_type": _PATH_TYPES},
        int_ranges={"precision": (0, None)},
    ),
    "gm_create_tileset": _create_model(
        "tileset",
        asset_names={"name": "tileset", "sprite_id": "sprite"},
        resource_names=("sprite_id",),
        int_ranges={
            "tile_width": (1, None),
            "tile_height": (1, None),
            "tile_xsep": (0, None),
            "tile_ysep": (0, None),
            "tile_xoff": (0, None),
            "tile_yoff": (0, None),
        },
    ),
    "gm_create_timeline": _create_model("timeline"),
    "gm_create_sequence": _create_model(
        "sequence",
        float_ranges={"length": (0.0, None), "playback_speed": (0.0, None)},
    ),
    "gm_create_note": _create_model("note"),
    "gm_event_add": _model(
        writes=True,
        required=("object", "event"),
        asset_names={"object": "object"},
        event_specs=("event",),
    ),
    "gm_event_remove": _model(
        writes=True,
        required=("object", "event"),
        asset_names={"object": "object"},
        event_specs=("event",),
    ),
    "gm_event_duplicate": _model(
        writes=True,
        required=("object", "source_event", "target_event"),
        asset_names={"object": "object"},
        event_specs=("source_event", "target_event"),
    ),
    "gm_event_fix": _model(writes=True, required=("object",), asset_names={"object": "object"}),
    "gm_room_ops_duplicate": _model(
        writes=True,
        required=("source_room", "new_name"),
        asset_names={"source_room": "room", "new_name": "room"},
    ),
    "gm_room_ops_rename": _model(
        writes=True,
        required=("room_name", "new_name"),
        asset_names={"room_name": "room", "new_name": "room"},
    ),
    "gm_room_ops_delete": _model(writes=True, required=("room_name",), asset_names={"room_name": "room"}),
    "gm_room_layer_add": _model(
        writes=True,
        required=("room_name", "layer_type", "layer_name"),
        asset_names={"room_name": "room"},
        resource_names=("layer_name",),
        choices={"layer_type": _LAYER_TYPES},
        int_ranges={"depth": (None, None)},
    ),
    "gm_room_layer_remove": _model(
        writes=True,
        required=("room_name", "layer_name"),
        asset_names={"room_name": "room"},
        resource_names=("layer_name",),
    ),
    "gm_room_instance_add": _model(
        writes=True,
        required=("room_name", "object_name", "x", "y"),
        asset_names={"room_name": "room", "object_name": "object"},
        resource_names=("layer",),
        float_ranges={"x": (None, None), "y": (None, None)},
    ),
    "gm_room_instance_remove": _model(
        writes=True,
        required=("room_name", "instance_id"),
        asset_names={"room_name": "room"},
        resource_names=("instance_id",),
    ),
    "gm_safe_delete": _model(
        writes=True,
        required=("asset_type", "asset_name"),
        choices={"asset_type": _ASSET_TYPES},
        dynamic_asset_names={"asset_name": "asset_type"},
    ),
    "gm_workflow_duplicate": _model(
        writes=True,
        required=("asset_path", "new_name"),
        asset_paths={"asset_path": None},
        inferred_asset_names={"new_name": "asset_path"},
    ),
    "gm_workflow_rename": _model(
        writes=True,
        required=("asset_path", "new_name"),
        asset_paths={"asset_path": None},
        inferred_asset_names={"new_name": "asset_path"},
    ),
    "gm_workflow_swap_sprite": _model(
        writes=True,
        required=("asset_path", "png"),
        asset_paths={"asset_path": "sprite"},
        png_paths=("png",),
        int_ranges={"frame": (0, None)},
    ),
    "gm_sprite_add_frame": _model(
        writes=True,
        required=("sprite_path",),
        asset_paths={"sprite_path": "sprite"},
        png_paths=("source_png",),
        int_ranges={"position": (-1, None)},
    ),
    "gm_sprite_remove_frame": _model(
        writes=True,
        required=("sprite_path", "position"),
        asset_paths={"sprite_path": "sprite"},
        int_ranges={"position": (0, None)},
    ),
    "gm_sprite_duplicate_frame": _model(
        writes=True,
        required=("sprite_path", "source_position"),
        asset_paths={"sprite_path": "sprite"},
        int_ranges={"source_position": (0, None), "target_position": (-1, None)},
    ),
    "gm_sprite_import_strip": _model(
        writes=True,
        required=("name", "source"),
        asset_names={"name": "sprite"},
        parent_paths=("parent_path",),
        png_paths=("source",),
        choices={"layout": _SPRITE_STRIP_LAYOUTS},
        int_ranges={"frame_width": (0, None), "frame_height": (0, None), "columns": (0, None)},
    ),
    "gm_texture_group_create": _model(
        writes=True,
        required=("name", "template"),
        group_names=("name", "template"),
        object_maps=("patch",),
    ),
    "gm_texture_group_update": _model(
        writes=True,
        required=("name", "patch"),
        group_names=("name",),
        object_maps=("patch",),
        string_lists={"configs": None},
    ),
    "gm_texture_group_rename": _model(
        writes=True,
        required=("old_name", "new_name"),
        group_names=("old_name", "new_name"),
    ),
    "gm_texture_group_delete": _model(
        writes=True,
        required=("name",),
        group_names=("name", "reassign_to"),
    ),
    "gm_texture_group_assign": _model(
        writes=True,
        required=("group_name",),
        group_names=("group_name", "from_group"),
        choices={"asset_type": _ASSET_TYPES},
        string_lists={"asset_identifiers": None, "configs": None},
        non_empty_strings=("name_contains", "folder_prefix"),
    ),
}


def _path_like(value: str) -> bool:
    windows_path = PureWindowsPath(value)
    return (
        Path(value).is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    )


def _validate_resource_name(value: Any, label: str, errors: ValidationErrorList) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    if _path_like(candidate) or candidate.endswith(".yy"):
        errors.append({"field": label, "message": "must be a resource name, not a path"})


def _validate_group_name(value: Any, label: str, errors: ValidationErrorList) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    if _path_like(candidate) or candidate.endswith(".yy"):
        errors.append({"field": label, "message": "must be a texture group name, not a path"})


def _asset_type_from_path(value: Any) -> str | None:
    normalized = str(value).strip().replace("\\", "/")
    parts = tuple(part for part in normalized.split("/") if part)
    if not parts:
        return None
    if parts[0] == "folders":
        return "folder"
    return _ASSET_PATH_TYPES.get(parts[0])


def _validate_asset_name(
    value: Any,
    label: str,
    asset_type: str,
    errors: ValidationErrorList,
    *,
    project_root: Any = None,
    allow_constructor: bool = False,
) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    if asset_type != "folder" and (_path_like(candidate) or candidate.endswith(".yy")):
        errors.append({"field": label, "message": f"must be a {asset_type} name, not a path"})
        return
    if asset_type == "folder":
        folder_path = Path(candidate.replace("\\", "/"))
        if Path(candidate).is_absolute() or any(part in {"", ".", ".."} for part in folder_path.parts):
            errors.append({"field": label, "message": "must be a safe GameMaker folder name"})
            return

    try:
        from gms_helpers.naming_config import get_config
        from gms_helpers.utils import validate_name

        config = get_config(project_root) if project_root not in (None, "") else None
        validate_name(candidate, asset_type, allow_constructor=allow_constructor, config=config)
    except ValueError as exc:
        errors.append({"field": label, "message": str(exc)})


def _validate_asset_path(value: Any, label: str, errors: ValidationErrorList, *, asset_type: str | None = None) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    path = Path(candidate)
    windows_path = PureWindowsPath(candidate)
    parts = tuple(part for part in candidate.replace("\\", "/").split("/") if part)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in Path(candidate.replace("\\", "/")).parts)
    ):
        errors.append({"field": label, "message": "must be a safe project-relative path"})
    if not candidate.replace("\\", "/").endswith(".yy"):
        errors.append({"field": label, "message": "must point to a .yy asset file"})
    detected_type = _asset_type_from_path(candidate)
    if detected_type is None:
        errors.append({"field": label, "message": "must point to a supported GameMaker asset path"})
    if asset_type and detected_type != asset_type:
        errors.append({"field": label, "message": f"must point to a {asset_type} asset"})
    if detected_type != "folder" and len(parts) != 3:
        errors.append({"field": label, "message": "must use the asset path form type/name/name.yy"})
    if detected_type == "folder" and not candidate.replace("\\", "/").startswith("folders/"):
        errors.append({"field": label, "message": "folder paths must start with folders/"})


def _validate_png_path(
    value: Any,
    label: str,
    errors: ValidationErrorList,
    *,
    project_root: Any = None,
) -> None:
    if value in (None, ""):
        return
    candidate = str(value).strip()
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    if "\x00" in candidate:
        errors.append({"field": label, "message": "must not contain null bytes"})
    if not candidate.lower().endswith(".png"):
        errors.append({"field": label, "message": "must point to a PNG file"})
    normalized = candidate.replace("\\", "/")
    path = Path(normalized)
    windows_path = PureWindowsPath(candidate)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or bool(windows_path.root)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        errors.append({"field": label, "message": "must be a safe project-relative PNG path"})
        return
    if project_root not in (None, ""):
        try:
            project_child_path(candidate, project_root=Path(project_root), kind="PNG source")
        except (OSError, ValueError, ValidationError):
            errors.append({"field": label, "message": "must resolve inside the approved project"})


def _validate_parent_path(value: Any, label: str, errors: ValidationErrorList, *, project_root: Any = None) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        return
    normalized = candidate.replace("\\", "/")
    path = Path(normalized)
    windows_path = PureWindowsPath(candidate)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        errors.append({"field": label, "message": "must be a safe project-relative folder path"})
        return
    if not (normalized.startswith("folders/") and normalized.endswith(".yy")):
        errors.append({"field": label, "message": "must be empty or a GameMaker folder path like folders/Foo.yy"})
        return
    if project_root not in (None, ""):
        try:
            from gms_helpers.exceptions import GMSError
            from gms_helpers.utils import validate_parent_path_for_project

            validate_parent_path_for_project(project_root, normalized)
        except GMSError as exc:
            errors.append({"field": label, "message": str(exc)})


def _validate_folder_path(value: Any, label: str, errors: ValidationErrorList) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    normalized = candidate.replace("\\", "/")
    path = Path(normalized)
    windows_path = PureWindowsPath(candidate)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        errors.append({"field": label, "message": "must be a safe project-relative folder path"})
        return
    if not (normalized.startswith("folders/") and normalized.endswith(".yy")):
        errors.append({"field": label, "message": "must be a GameMaker folder path like folders/Foo.yy"})


def _validate_event_spec(value: Any, label: str, errors: ValidationErrorList) -> None:
    try:
        from gms_helpers.event_model import parse_event_spec
        from gms_helpers.exceptions import GMSError

        parse_event_spec(value)
    except GMSError as exc:
        errors.append({"field": label, "message": str(exc)})


def _validate_collision_target_exists(arguments: Mapping[str, Any], field: str, errors: ValidationErrorList) -> None:
    project_root = arguments.get("project_root")
    if project_root in (None, "") or field not in arguments:
        return
    try:
        from gms_helpers.event_model import parse_event_spec, resolve_collision_object_reference
        from gms_helpers.exceptions import GMSError

        spec = parse_event_spec(arguments[field])
        if spec.collision_object is not None:
            resolve_collision_object_reference(project_root, spec.collision_object)
    except GMSError as exc:
        if not any(error["field"] == field for error in errors):
            errors.append({"field": field, "message": str(exc)})


def _validate_duplicate_event_pair(arguments: Mapping[str, Any], errors: ValidationErrorList) -> None:
    if "source_event" not in arguments or "target_event" not in arguments:
        return
    try:
        from gms_helpers.event_model import parse_event_spec
        from gms_helpers.exceptions import GMSError

        source = parse_event_spec(arguments["source_event"])
        target = parse_event_spec(arguments["target_event"])
        if source.event_type != target.event_type:
            errors.append({"field": "target_event", "message": "must use the same event type as source_event"})
    except GMSError:
        return


def _validate_choices(args: Mapping[str, Any], field: str, choices: Iterable[Any], errors: ValidationErrorList) -> None:
    if field not in args or args[field] in (None, ""):
        return
    value = args[field]
    if value not in choices and str(value) not in choices:
        printable = ", ".join(str(choice) for choice in sorted(choices, key=str))
        errors.append({"field": field, "message": f"must be one of: {printable}"})


def _validate_bool(args: Mapping[str, Any], field: str, errors: ValidationErrorList) -> None:
    if field not in args or args[field] is None:
        return
    if not isinstance(args[field], bool):
        errors.append({"field": field, "message": "must be a boolean"})


def _validate_int_range(
    args: Mapping[str, Any], field: str, minimum: int | None, maximum: int | None, errors: ValidationErrorList
) -> None:
    if field not in args or args[field] is None:
        return
    value = args[field]
    if isinstance(value, bool):
        errors.append({"field": field, "message": "must be an integer"})
        return
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors.append({"field": field, "message": "must be an integer"})
        return
    if minimum is not None and parsed < minimum:
        if minimum == 0:
            errors.append({"field": field, "message": "must not be negative"})
        elif minimum == 1:
            errors.append({"field": field, "message": "must be greater than zero"})
        else:
            errors.append({"field": field, "message": f"must be at least {minimum}"})
    if maximum is not None and parsed > maximum:
        errors.append({"field": field, "message": f"must be at most {maximum}"})


def _validate_float_range(
    args: Mapping[str, Any], field: str, minimum: float | None, maximum: float | None, errors: ValidationErrorList
) -> None:
    if field not in args or args[field] is None:
        return
    value = args[field]
    if isinstance(value, bool):
        errors.append({"field": field, "message": "must be a number"})
        return
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        errors.append({"field": field, "message": "must be a number"})
        return
    if not math.isfinite(parsed):
        errors.append({"field": field, "message": "must be a finite number"})
        return
    if minimum is not None and parsed < minimum:
        errors.append({"field": field, "message": f"must be at least {minimum:g}"})
    if maximum is not None and parsed > maximum:
        errors.append({"field": field, "message": f"must be at most {maximum:g}"})


def _validate_string_list(
    args: Mapping[str, Any],
    field: str,
    choices: frozenset[str] | None,
    errors: ValidationErrorList,
) -> None:
    if field not in args or args[field] is None:
        return
    value = args[field]
    if not isinstance(value, list):
        errors.append({"field": field, "message": "must be a list"})
        return
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append({"field": f"{field}[{index}]", "message": "must be a non-empty string"})
            continue
        if choices is not None and item not in choices:
            errors.append({"field": f"{field}[{index}]", "message": "contains an unsupported value"})


def _validate_object_map(args: Mapping[str, Any], field: str, errors: ValidationErrorList) -> None:
    if field not in args or args[field] is None:
        return
    value = args[field]
    if not isinstance(value, dict):
        errors.append({"field": field, "message": "must be an object"})
        return
    for key in value:
        if not isinstance(key, str) or not key.strip():
            errors.append({"field": field, "message": "must only contain non-empty string keys"})
            return


def _validate_non_empty_string(args: Mapping[str, Any], field: str, errors: ValidationErrorList) -> None:
    if field not in args or args[field] in (None, ""):
        return
    if not isinstance(args[field], str):
        errors.append({"field": field, "message": "must be a string"})
        return
    if not args[field].strip():
        errors.append({"field": field, "message": "must not be empty"})


def _validate_asset_identifiers(value: Any, errors: ValidationErrorList) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        errors.append({"field": "asset_identifiers", "message": "must be a list"})
        return
    for index, item in enumerate(value):
        candidate = str(item)
        windows_path = PureWindowsPath(candidate)
        if (
            not candidate.strip()
            or Path(candidate).is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or ".." in Path(candidate).parts
        ):
            errors.append({"field": f"asset_identifiers[{index}]", "message": "must be a safe resource name or path"})


def _validate_operation_model(model: OperationModel, arguments: Mapping[str, Any]) -> ValidationErrorList:
    errors: ValidationErrorList = []
    project_root = arguments.get("project_root")

    for field_name in sorted(model.required):
        if field_name not in arguments or arguments[field_name] in (None, ""):
            errors.append({"field": field_name, "message": "is required"})

    for field_name in sorted(_BOOLEAN_FIELDS.intersection(arguments.keys())):
        _validate_bool(arguments, field_name, errors)

    for field_name in sorted(model.resource_names):
        if field_name in arguments and arguments[field_name] not in (None, ""):
            _validate_resource_name(arguments[field_name], field_name, errors)

    for field_name in sorted(model.group_names):
        if field_name in arguments and arguments[field_name] not in (None, ""):
            _validate_group_name(arguments[field_name], field_name, errors)

    for field_name, asset_type in model.asset_names.items():
        if field_name in arguments and arguments[field_name] not in (None, ""):
            allow_constructor = asset_type == "script" and bool(arguments.get("is_constructor"))
            _validate_asset_name(
                arguments[field_name],
                field_name,
                asset_type,
                errors,
                project_root=project_root,
                allow_constructor=allow_constructor,
            )

    for field_name, asset_type_field in model.dynamic_asset_names.items():
        asset_type = str(arguments.get(asset_type_field) or "")
        if asset_type in _ASSET_TYPES and field_name in arguments and arguments[field_name] not in (None, ""):
            _validate_asset_name(arguments[field_name], field_name, asset_type, errors, project_root=project_root)

    for field_name, path_field in model.inferred_asset_names.items():
        asset_type = _asset_type_from_path(arguments.get(path_field))
        if asset_type and field_name in arguments and arguments[field_name] not in (None, ""):
            _validate_asset_name(arguments[field_name], field_name, asset_type, errors, project_root=project_root)

    for field_name in sorted(model.parent_paths):
        if field_name in arguments:
            _validate_parent_path(arguments[field_name], field_name, errors, project_root=project_root)

    for field_name in sorted(model.folder_paths):
        if field_name in arguments:
            _validate_folder_path(arguments[field_name], field_name, errors)

    for field_name, asset_type in model.asset_paths.items():
        if field_name in arguments:
            _validate_asset_path(arguments[field_name], field_name, errors, asset_type=asset_type)

    for field_name in sorted(model.png_paths):
        if field_name in arguments:
            _validate_png_path(arguments[field_name], field_name, errors, project_root=project_root)

    for field_name in sorted(model.event_specs):
        if field_name in arguments:
            _validate_event_spec(arguments[field_name], field_name, errors)

    for field_name, choices in model.choices.items():
        _validate_choices(arguments, field_name, choices, errors)

    for field_name, (minimum, maximum) in model.int_ranges.items():
        _validate_int_range(arguments, field_name, minimum, maximum, errors)

    for field_name, (minimum, maximum) in model.float_ranges.items():
        _validate_float_range(arguments, field_name, minimum, maximum, errors)

    for field_name, choices in model.string_lists.items():
        _validate_string_list(arguments, field_name, choices, errors)

    for field_name in sorted(model.object_maps):
        _validate_object_map(arguments, field_name, errors)

    for field_name in sorted(model.non_empty_strings):
        _validate_non_empty_string(arguments, field_name, errors)

    return errors


def _validate_legacy_generic(tool_name: str, arguments: Mapping[str, Any]) -> ValidationErrorList:
    errors: ValidationErrorList = []

    for field_name in _RESOURCE_NAME_PARAMS:
        if field_name in arguments and arguments[field_name] not in (None, ""):
            _validate_resource_name(arguments[field_name], field_name, errors)

    if "name" in arguments and tool_name.startswith(_NAME_TOOLS_PREFIXES) and arguments["name"] not in (None, ""):
        _validate_resource_name(arguments["name"], "name", errors)

    if "asset_path" in arguments:
        _validate_asset_path(arguments["asset_path"], "asset_path", errors)

    for field_name in ("parent_path",):
        if field_name in arguments:
            _validate_parent_path(arguments[field_name], field_name, errors, project_root=arguments.get("project_root"))

    for field_name in ("event", "source_event"):
        if field_name in arguments:
            _validate_event_spec(arguments[field_name], field_name, errors)

    for field_name in ("asset_type",):
        _validate_choices(arguments, field_name, _ASSET_TYPES, errors)
    _validate_choices(arguments, "layer_type", _LAYER_TYPES, errors)
    _validate_choices(arguments, "output_mode", _OUTPUT_MODES, errors)
    if tool_name == "gm_diagnostics":
        _validate_choices(arguments, "depth", _DIAGNOSTIC_DEPTHS, errors)
    _validate_choices(arguments, "scope", _REFERENCE_SCOPES, errors)
    _validate_choices(arguments, "runtime", _RUNTIMES, errors)
    _validate_choices(arguments, "platform", _PLATFORMS, errors)

    for field_name in ("width", "height", "frame_count", "tile_width", "tile_height", "max_results"):
        _validate_int_range(arguments, field_name, 1, None, errors)
    _validate_int_range(arguments, "tail_lines", 0, None, errors)
    _validate_int_range(arguments, "timeout_seconds", 0, None, errors)
    if tool_name != "gm_diagnostics":
        _validate_int_range(arguments, "depth", 0, None, errors)

    return errors


def validate_mcp_tool_arguments(tool_name: str, arguments: Mapping[str, Any]) -> ValidationErrorList:
    """Return MCP boundary validation errors for a tool call."""
    model = _OPERATION_MODELS.get(tool_name)
    if model is not None:
        errors = _validate_operation_model(model, arguments)
    else:
        errors = _validate_legacy_generic(tool_name, arguments)

    _validate_choices(arguments, "output_mode", _OUTPUT_MODES, errors)
    _validate_int_range(arguments, "tail_lines", 0, None, errors)
    _validate_int_range(arguments, "timeout_seconds", 0, None, errors)
    _validate_asset_identifiers(arguments.get("asset_identifiers"), errors)
    if tool_name == "gm_event_add":
        _validate_collision_target_exists(arguments, "event", errors)
    elif tool_name == "gm_event_duplicate":
        _validate_duplicate_event_pair(arguments, errors)
        _validate_collision_target_exists(arguments, "source_event", errors)
        _validate_collision_target_exists(arguments, "target_event", errors)
    return errors


def invalid_arguments_result(tool_name: str, errors: ValidationErrorList) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": "Invalid MCP tool arguments",
        "tool": tool_name,
        "validation_errors": errors,
    }


def write_operation_model_names() -> tuple[str, ...]:
    """Return write tools covered by typed validation models."""
    return tuple(sorted(name for name, model in _OPERATION_MODELS.items() if model.writes))
