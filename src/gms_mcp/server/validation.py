"""MCP boundary validation for GameMaker tools."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, List, Mapping


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
_ASSET_TYPES = {
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
_LAYER_TYPES = {"background", "instance", "instances", "asset", "tile", "path", "effect"}
_OUTPUT_MODES = {"full", "tail", "none"}
_DIAGNOSTIC_DEPTHS = {"quick", "deep"}
_REFERENCE_SCOPES = {"all", "gml", "yy", "scripts", "objects", "extensions", "datafiles"}
_RUNTIMES = {"VM", "YYC", "vm", "yyc"}
_PLATFORMS = {"Windows", "macOS", "Linux", "HTML5", "Android", "iOS", "GX.games"}
_EVENT_TYPES = {
    "create",
    "destroy",
    "alarm",
    "step",
    "collision",
    "keyboard",
    "mouse",
    "other",
    "draw",
    "keypress",
    "keyrelease",
    "trigger",
    "cleanup",
    "gesture",
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


def _validate_resource_name(value: Any, label: str, errors: List[Dict[str, str]]) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    if _path_like(candidate) or candidate.endswith(".yy"):
        errors.append({"field": label, "message": "must be a resource name, not a path"})


def _validate_asset_path(value: Any, label: str, errors: List[Dict[str, str]]) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    path = Path(candidate)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        errors.append({"field": label, "message": "must be a safe project-relative path"})
    if not candidate.replace("\\", "/").endswith(".yy"):
        errors.append({"field": label, "message": "must point to a .yy asset file"})


def _validate_parent_path(value: Any, label: str, errors: List[Dict[str, str]]) -> None:
    candidate = str(value).strip() if value is not None else ""
    if not candidate:
        return
    if _path_like(candidate) and (Path(candidate).is_absolute() or ".." in Path(candidate).parts):
        errors.append({"field": label, "message": "must be a safe project-relative folder path"})
        return
    normalized = candidate.replace("\\", "/")
    if not (normalized.startswith("folders/") and normalized.endswith(".yy")):
        errors.append({"field": label, "message": "must be empty or a GameMaker folder path like folders/Foo.yy"})


def _validate_event_spec(value: Any, label: str, errors: List[Dict[str, str]]) -> None:
    candidate = str(value).strip().lower() if value is not None else ""
    if not candidate:
        errors.append({"field": label, "message": "must not be empty"})
        return
    parts = candidate.split(":")
    if len(parts) > 2 or parts[0] not in _EVENT_TYPES:
        errors.append({"field": label, "message": "must be an event type like create or step:0"})
        return
    if len(parts) == 2:
        try:
            int(parts[1])
        except ValueError:
            errors.append({"field": label, "message": "event number must be an integer"})


def _validate_choices(
    args: Mapping[str, Any], field: str, choices: Iterable[str], errors: List[Dict[str, str]]
) -> None:
    if field not in args or args[field] in (None, ""):
        return
    if str(args[field]) not in choices:
        errors.append({"field": field, "message": f"must be one of: {', '.join(sorted(choices))}"})


def _validate_positive_int(args: Mapping[str, Any], field: str, errors: List[Dict[str, str]]) -> None:
    if field not in args or args[field] is None:
        return
    try:
        value = int(args[field])
    except (TypeError, ValueError):
        errors.append({"field": field, "message": "must be an integer"})
        return
    if value < 1:
        errors.append({"field": field, "message": "must be greater than zero"})


def _validate_non_negative_int(args: Mapping[str, Any], field: str, errors: List[Dict[str, str]]) -> None:
    if field not in args or args[field] is None:
        return
    try:
        value = int(args[field])
    except (TypeError, ValueError):
        errors.append({"field": field, "message": "must be an integer"})
        return
    if value < 0:
        errors.append({"field": field, "message": "must not be negative"})


def validate_mcp_tool_arguments(tool_name: str, arguments: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Return MCP boundary validation errors for a tool call."""
    errors: List[Dict[str, str]] = []

    for field in _RESOURCE_NAME_PARAMS:
        if field in arguments and arguments[field] not in (None, ""):
            _validate_resource_name(arguments[field], field, errors)

    if "name" in arguments and tool_name.startswith(_NAME_TOOLS_PREFIXES) and arguments["name"] not in (None, ""):
        _validate_resource_name(arguments["name"], "name", errors)

    if "asset_path" in arguments:
        _validate_asset_path(arguments["asset_path"], "asset_path", errors)

    for field in ("parent_path",):
        if field in arguments:
            _validate_parent_path(arguments[field], field, errors)

    for field in ("event", "source_event"):
        if field in arguments:
            _validate_event_spec(arguments[field], field, errors)

    for field in ("asset_type",):
        _validate_choices(arguments, field, _ASSET_TYPES, errors)
    _validate_choices(arguments, "layer_type", _LAYER_TYPES, errors)
    _validate_choices(arguments, "output_mode", _OUTPUT_MODES, errors)
    if tool_name == "gm_diagnostics":
        _validate_choices(arguments, "depth", _DIAGNOSTIC_DEPTHS, errors)
    _validate_choices(arguments, "scope", _REFERENCE_SCOPES, errors)
    _validate_choices(arguments, "runtime", _RUNTIMES, errors)
    _validate_choices(arguments, "platform", _PLATFORMS, errors)

    for field in ("width", "height", "frame_count", "tile_width", "tile_height", "max_results"):
        _validate_positive_int(arguments, field, errors)
    _validate_non_negative_int(arguments, "tail_lines", errors)
    _validate_non_negative_int(arguments, "timeout_seconds", errors)
    if tool_name != "gm_diagnostics":
        _validate_non_negative_int(arguments, "depth", errors)

    asset_identifiers = arguments.get("asset_identifiers")
    if asset_identifiers is not None:
        if not isinstance(asset_identifiers, list):
            errors.append({"field": "asset_identifiers", "message": "must be a list"})
        else:
            for index, item in enumerate(asset_identifiers):
                candidate = str(item)
                if not candidate.strip() or Path(candidate).is_absolute() or ".." in Path(candidate).parts:
                    errors.append(
                        {"field": f"asset_identifiers[{index}]", "message": "must be a safe resource name or path"}
                    )

    return errors


def invalid_arguments_result(tool_name: str, errors: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": "Invalid MCP tool arguments",
        "tool": tool_name,
        "validation_errors": errors,
    }
