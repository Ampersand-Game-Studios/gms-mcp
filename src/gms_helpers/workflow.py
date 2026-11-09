#!/usr/bin/env python3
"""workflow.py - High-level project utilities (Part C)

This module provides advanced helper features on top of the basic CRUD
implemented in asset_helper.py.  All functions are intentionally thin and
focus on filesystem / .yyp manipulation.  They **never** call GameMaker
proper; they work purely on raw files.

Implemented Features:
    C-1 duplicate_asset
    C-2 rename_asset
    C-3 delete_asset
    C-4 swap_sprite_png
    C-5 lint_project

Optional Extras:
    - Colourised output (colorama)
    - Global `yes` flag handled by callers (cli_ext)
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# Direct imports - no complex fallbacks needed
from .path_safety import project_child_path, validate_resource_name
from .utils import (
    load_json_loose,
    save_pretty_json_gm,
    find_yyp,
    insert_into_resources,
    generate_uuid,
)
from .asset_types import ASSET_TYPES
from .base_asset import preflight_asset_destination, require_asset_destination_available
from .exceptions import (
    AssetExistsError,
    AssetNotFoundError,
    InvalidAssetTypeError,
    JSONParseError,
    ValidationError,
)
from .results import OperationResult, AssetResult, MaintenanceResult
from .transactions import (
    transaction_is_active,
    transactional_copy2,
    transactional_copytree,
    transactional_rename,
    transactional_replace,
    transactional_rmtree,
    transactional_unlink,
)

# ---------------------------------------------------------------------------
# Optional color output
# ---------------------------------------------------------------------------


def _try_import(name: str):
    try:
        return __import__(name)
    except ModuleNotFoundError:
        return None


colorama = _try_import("colorama")
if colorama:
    colorama.init()


def _c(text: str, colour: str | None = None):
    """Return colorised text if colorama is present & output is a TTY."""
    if not sys.stdout.isatty() or not colorama or not colour:
        return text
    return getattr(colorama.Fore, colour.upper(), "") + text + colorama.Style.RESET_ALL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_from_path(project_root: Path, asset_path: str):
    """Return (asset_type, asset_folder_path, asset_name) using .yyp-style path.

    The name is the ``.yy`` stem and the folder is the path's own directory:
    IDE-created assets use exact-case folders, tool-created ones lower-case.
    Callers confirm the path against its ``.yyp`` registration.
    """
    project_root = Path(project_root).resolve()
    p = Path(asset_path)
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise InvalidAssetTypeError(f"Invalid asset path '{asset_path}'. Path traversal is not allowed.")
    if len(p.parts) < 2:
        raise InvalidAssetTypeError(f"Invalid asset path '{asset_path}'. Expected '<folder>/<name>/<name>.yy'.")
    plural = p.parts[0]
    mapping = {
        "scripts": "script",
        "objects": "object",
        "sprites": "sprite",
        "rooms": "room",
        "folders": "folder",
        "fonts": "font",
        "shaders": "shader",
        "animcurves": "animcurve",
        "sounds": "sound",
        "paths": "path",
        "tilesets": "tileset",
        "timelines": "timeline",
        "sequences": "sequence",
        "notes": "note",
    }
    asset_type = mapping.get(plural, plural)
    if asset_type not in ASSET_TYPES:
        raise InvalidAssetTypeError(f"Unrecognised asset path prefix '{plural}'.")
    if plural == "folders":
        if len(p.parts) != 2 or p.suffix != ".yy":
            raise InvalidAssetTypeError(f"Invalid folder path '{asset_path}'. Expected 'folders/<name>.yy'.")
        asset_name = p.stem
        folder_path = (project_root / plural / p.parts[1]).resolve()
    else:
        if len(p.parts) != 3 or p.suffix != ".yy" or p.parts[1].casefold() != p.stem.casefold():
            raise InvalidAssetTypeError(f"Invalid asset path '{asset_path}'. Expected '<folder>/<name>/<name>.yy'.")
        asset_name = p.stem
        folder_path = (project_root / plural / p.parts[1]).resolve()
    try:
        folder_path.relative_to(project_root)
    except ValueError as exc:
        raise InvalidAssetTypeError(
            f"Invalid asset path '{asset_path}'. Resolved path escapes the project root."
        ) from exc
    return asset_type, folder_path, asset_name


def _validate_asset_name(name: str) -> str:
    candidate = str(name).strip()
    path = Path(candidate)
    if not candidate or path.is_absolute() or len(path.parts) != 1 or candidate in {".", ".."}:
        raise InvalidAssetTypeError(f"Invalid asset name '{name}'. Path separators are not allowed.")
    return candidate


_ASSET_DIRECTORIES = {
    "animcurve": "animcurves",
    "font": "fonts",
    "folder": "folders",
    "note": "notes",
    "object": "objects",
    "path": "paths",
    "room": "rooms",
    "script": "scripts",
    "sequence": "sequences",
    "shader": "shaders",
    "sound": "sounds",
    "sprite": "sprites",
    "tileset": "tilesets",
    "timeline": "timelines",
}


def _asset_directory(asset_type: str) -> str:
    return _ASSET_DIRECTORIES.get(asset_type, f"{asset_type}s")


# Files GameMaker names after the resource; they move with a rename/duplicate.
# (Sound and font files are referenced by explicit .yy fields instead.)
_NAMED_SIDECARS = {
    "script": (".gml",),
    "shader": (".vsh", ".fsh"),
    "note": (".txt",),
}


def _rename_named_sidecars(asset_folder: Path, asset_type: str, old_name: str, new_name: str) -> List[str]:
    """Rename resource-named companion files; return the new file names."""
    renamed: List[str] = []
    for extension in _NAMED_SIDECARS.get(asset_type, ()):
        source = asset_folder / f"{old_name}{extension}"
        if not source.exists():
            continue
        destination = asset_folder / f"{new_name}{extension}"
        if destination.exists():
            raise AssetExistsError(f"Cannot rename {source.name}; destination exists: {destination}")
        transactional_rename(source, destination)
        if extension == ".gml":
            _patch_gml_stub(destination, old_name, new_name)
        renamed.append(destination.name)
    return renamed


def _refuse_duplicate_global_declarations(script_folder: Path, script_name: str) -> None:
    """Functions, macros and enums declared by a script are global in GML."""
    from .reference_scanner import find_gml_global_declarations, read_gml_source

    source_gml = script_folder / f"{script_name}.gml"
    if not source_gml.exists():
        return
    clashes = [
        f"{kind} {name}"
        for kind, name in find_gml_global_declarations(read_gml_source(source_gml))
        if not (kind == "function" and name == script_name)
    ]
    if clashes:
        raise ValidationError(
            f"Duplicate blocked: script '{script_name}' declares global {', '.join(sorted(set(clashes)))}; "
            "a copy would declare them twice. Move them to their own script or rename them in the copy's source first."
        )


def _registered_owners(project_root: Path) -> Dict[str, Tuple[str, str]]:
    """Map each registered asset's directory to its (name, registered .yy path)."""
    yyp_data = load_json_loose(find_yyp(project_root))
    owners: Dict[str, Tuple[str, str]] = {}
    for entry in yyp_data.get("resources", []) if isinstance(yyp_data, dict) else []:
        identity = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(identity, dict):
            continue
        name, path = identity.get("name"), identity.get("path")
        if isinstance(name, str) and isinstance(path, str):
            path = path.replace("\\", "/")
            owners[path.rsplit("/", 1)[0]] = (name, path)
    return owners


def _replace_identity_values(value: Any, replacements: Dict[str, str]) -> Any:
    """Replace known local identity tokens throughout copied metadata."""
    if isinstance(value, list):
        return [_replace_identity_values(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_identity_values(item, replacements) for key, item in value.items()}
    if isinstance(value, str):
        rewritten = value
        for old_identity, new_identity in replacements.items():
            rewritten = rewritten.replace(old_identity, new_identity)
        return rewritten
    return value


def _collect_keyframe_ids(value: Any, identities: Dict[str, str]) -> None:
    """Collect GameMaker keyframe IDs that must be unique in copied assets."""
    if isinstance(value, list):
        for item in value:
            _collect_keyframe_ids(item, identities)
        return
    if not isinstance(value, dict):
        return
    identity = value.get("id")
    if isinstance(identity, str) and re.fullmatch(r"[0-9a-fA-F]{32}", identity):
        identities.setdefault(identity, generate_uuid())
    for item in value.values():
        _collect_keyframe_ids(item, identities)


def _regenerate_duplicate_identities(asset_type: str, yy_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Regenerate local IDs whose uniqueness is part of GameMaker's format."""
    identities: Dict[str, str] = {}

    if asset_type == "sprite":
        for frame in yy_data.get("frames", []):
            if isinstance(frame, dict):
                identity = frame.get("name")
                if isinstance(identity, str) and identity:
                    identities.setdefault(identity, generate_uuid())
        for layer in yy_data.get("layers", []):
            if isinstance(layer, dict):
                identity = layer.get("name")
                if isinstance(identity, str) and identity:
                    identities.setdefault(identity, generate_uuid())
        _collect_keyframe_ids(yy_data.get("sequence"), identities)

    if asset_type == "room":

        def collect_instances(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    collect_instances(item)
                return
            if not isinstance(value, dict):
                return
            # Inherited instances keep the parent room's identity; renaming them
            # would break inheritedItemId and parent-path creation-order entries.
            inherited = isinstance(value.get("inheritedItemId"), dict)
            if not inherited and (value.get("resourceType") == "GMRInstance" or "$GMRInstance" in value):
                identity = value.get("name")
                if isinstance(identity, str) and identity.startswith("inst_"):
                    identities.setdefault(identity, f"inst_{generate_uuid()}")
            for item in value.values():
                collect_instances(item)

        collect_instances(yy_data.get("layers", []))

    if asset_type in {"animcurve", "sequence", "sprite", "timeline"}:
        _collect_keyframe_ids(yy_data, identities)

    return _replace_identity_values(yy_data, identities), identities


def _rename_identity_paths(asset_folder: Path, replacements: Dict[str, str]) -> None:
    """Rename copied files/directories whose names contain regenerated IDs."""
    if not replacements:
        return
    for path in sorted(asset_folder.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        new_name = path.name
        for old_identity, new_identity in replacements.items():
            new_name = new_name.replace(old_identity, new_identity)
        if new_name != path.name:
            destination = path.with_name(new_name)
            if destination.exists():
                raise AssetExistsError(f"Cannot regenerate duplicate identity; destination exists: {destination}")
            transactional_rename(path, destination)


def _validate_registered_asset(
    project_root: Path,
    asset_path: str,
    asset_name: str,
    *,
    sidecars: List[str] | None = None,
    stale_names: Tuple[str, ...] = (),
) -> List[str]:
    """Return scoped consistency errors for one registered GameMaker asset."""
    errors: List[str] = []
    yy_path = project_root / asset_path
    if not yy_path.exists():
        errors.append(f"Asset file is missing: {asset_path}")
        return errors
    for sidecar in sidecars or []:
        if not (yy_path.parent / sidecar).is_file():
            errors.append(f"Asset companion file is missing: {sidecar}")
    for stale in stale_names:
        if (yy_path.parent / stale).exists():
            errors.append(f"Asset still has a file named after the old resource: {stale}")
    yy_data = load_json_loose(yy_path)
    if not isinstance(yy_data, dict):
        errors.append(f"Asset JSON is invalid: {asset_path}")
        return errors
    if yy_data.get("name") != asset_name:
        errors.append(f"Asset metadata name is {yy_data.get('name')!r}, expected {asset_name!r}")
    if "%Name" in yy_data and yy_data.get("%Name") != asset_name:
        errors.append(f"Asset metadata %Name is {yy_data.get('%Name')!r}, expected {asset_name!r}")

    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if not isinstance(yyp_data, dict):
        errors.append(f"Project JSON is invalid: {yyp_path.name}")
        return errors
    matches = [
        entry
        for entry in yyp_data.get("resources", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), dict)
        and entry["id"].get("name") == asset_name
        and entry["id"].get("path") == asset_path
    ]
    if len(matches) != 1:
        errors.append(f"Expected one .yyp resource entry for {asset_name!r} at {asset_path!r}; found {len(matches)}")
    return errors


def _duplicate_order_entry(entry: Any, new_name: str, old_path: str, new_path: str) -> Any | None:
    """Clone one matching resource-order entry without changing unrelated fields."""

    if isinstance(entry, str):
        return new_path if entry.replace("\\", "/") == old_path else None
    if not isinstance(entry, dict):
        return None
    entry_path = entry.get("path")
    if not isinstance(entry_path, str) or entry_path.replace("\\", "/") != old_path:
        return None
    cloned = copy.deepcopy(entry)
    cloned["path"] = new_path.replace("/", "\\") if "\\" in entry_path else new_path
    if "name" in cloned:
        cloned["name"] = new_name
    return cloned


def _renumber_order_entries(entries: List[Any]) -> None:
    if any(isinstance(entry, dict) and isinstance(entry.get("order"), int) for entry in entries):
        for index, entry in enumerate(entries):
            if isinstance(entry, dict) and isinstance(entry.get("order"), int):
                entry["order"] = index


def _duplicate_resource_order_entries(
    project_root: Path,
    yyp_data: Dict[str, Any],
    new_name: str,
    old_path: str,
    new_path: str,
) -> None:
    """Add the duplicated resource beside its source in structured order metadata."""

    order_lists: List[Tuple[Path | None, Dict[str, Any], List[Any]]] = []
    yyp_order = yyp_data.get("resourceOrder")
    if isinstance(yyp_order, list):
        order_lists.append((None, yyp_data, yyp_order))

    for order_path in sorted(project_root.rglob("*.resource_order")):
        order_data = load_json_loose(order_path)
        if not isinstance(order_data, dict):
            raise JSONParseError(f"Could not load resource-order metadata: {order_path}")
        entries = order_data.get("ResourceOrderSettings")
        if isinstance(entries, list):
            order_lists.append((order_path, order_data, entries))

    for order_path, order_data, entries in order_lists:
        if any(_duplicate_order_entry(entry, new_name, new_path, new_path) is not None for entry in entries):
            raise AssetExistsError(f"Resource-order metadata already contains '{new_name}' at '{new_path}'.")
        updated: List[Any] = []
        for entry in entries:
            updated.append(entry)
            clone = _duplicate_order_entry(entry, new_name, old_path, new_path)
            if clone is not None:
                updated.append(clone)
        entries[:] = updated
        _renumber_order_entries(entries)
        if order_path is not None:
            save_pretty_json_gm(order_path, order_data)

    if old_path.startswith("rooms/") and new_path.startswith("rooms/"):
        room_order = yyp_data.setdefault("RoomOrderNodes", [])
        if not isinstance(room_order, list):
            raise JSONParseError("Project RoomOrderNodes must be a list")
        if any(
            isinstance(entry, dict)
            and isinstance(entry.get("roomId"), dict)
            and (
                entry["roomId"].get("name") == new_name
                or str(entry["roomId"].get("path", "")).replace("\\", "/") == new_path
            )
            for entry in room_order
        ):
            raise AssetExistsError(f"Room order already contains '{new_name}' at '{new_path}'.")
        new_node = {"roomId": {"name": new_name, "path": new_path}}
        source_index = next(
            (
                index
                for index, entry in enumerate(room_order)
                if isinstance(entry, dict)
                and isinstance(entry.get("roomId"), dict)
                and str(entry["roomId"].get("path", "")).replace("\\", "/") == old_path
            ),
            None,
        )
        room_order.insert(source_index + 1 if source_index is not None else len(room_order), new_node)


def _remove_resource_order_entries(
    project_root: Path,
    yyp_data: Dict[str, Any],
    asset_path: str,
) -> None:
    """Remove one resource from structured order metadata."""

    def keep(entry: Any) -> bool:
        if isinstance(entry, str):
            return entry.replace("\\", "/") != asset_path
        if not isinstance(entry, dict):
            return True
        path = entry.get("path")
        if not isinstance(path, str) or path.replace("\\", "/") != asset_path:
            return True
        return False

    yyp_order = yyp_data.get("resourceOrder")
    if isinstance(yyp_order, list):
        yyp_order[:] = [entry for entry in yyp_order if keep(entry)]
        _renumber_order_entries(yyp_order)

    if asset_path.startswith("rooms/"):
        room_order = yyp_data.get("RoomOrderNodes")
        if isinstance(room_order, list):
            room_order[:] = [
                entry
                for entry in room_order
                if not (
                    isinstance(entry, dict)
                    and isinstance(entry.get("roomId"), dict)
                    and str(entry["roomId"].get("path", "")).replace("\\", "/") == asset_path
                )
            ]

    for order_path in sorted(project_root.rglob("*.resource_order")):
        order_data = load_json_loose(order_path)
        if not isinstance(order_data, dict):
            raise JSONParseError(f"Could not load resource-order metadata: {order_path}")
        entries = order_data.get("ResourceOrderSettings")
        if not isinstance(entries, list):
            continue
        updated = [entry for entry in entries if keep(entry)]
        if updated == entries:
            continue
        entries[:] = updated
        _renumber_order_entries(entries)
        save_pretty_json_gm(order_path, order_data)


# ---------------------------------------------------------------------------
# C-1: Duplicate Asset
# ---------------------------------------------------------------------------


def duplicate_asset(project_root: Path, asset_path: str, new_name: str, *, yes: bool = False) -> AssetResult:
    project_root = Path(project_root).resolve()
    asset_type, src_folder, old_name = _asset_from_path(project_root, asset_path)
    new_name = _validate_asset_name(new_name)
    if asset_type == "folder":
        raise InvalidAssetTypeError("Folder resources cannot be duplicated with the asset workflow.")
    asset_dir = _asset_directory(asset_type)

    require_asset_destination_available(
        project_root=project_root,
        asset_type=asset_type,
        folder_prefix=asset_dir,
        name=new_name,
        operation="duplicate",
    )
    if asset_type == "script":
        _refuse_duplicate_global_declarations(src_folder, old_name)
    dst_folder = project_root / asset_dir / new_name.lower()
    source_yy = src_folder / f"{old_name}.yy"
    source_data = load_json_loose(source_yy)
    if not isinstance(source_data, dict):
        raise JSONParseError(f"Could not load {source_yy} for duplication")
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if not isinstance(yyp_data, dict):
        raise JSONParseError(f"Could not load {yyp_path} for updating")
    resources = yyp_data.setdefault("resources", [])
    source_entries = [
        entry
        for entry in resources
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), dict)
        and entry["id"].get("name") == old_name
        and entry["id"].get("path") == asset_path
    ]
    if len(source_entries) != 1:
        raise AssetNotFoundError(
            f"Expected one registered source asset '{old_name}' at '{asset_path}', found {len(source_entries)}."
        )
    if any(
        isinstance(entry, dict) and isinstance(entry.get("id"), dict) and entry["id"].get("name") == new_name
        for entry in resources
    ):
        raise AssetExistsError(f"A project resource named '{new_name}' already exists.")

    rel_path = f"{asset_dir}/{new_name.lower()}/{new_name}.yy"
    try:
        # Final read-only validation closes the gap between a Resolve choice
        # and the first filesystem mutation.
        require_asset_destination_available(
            project_root=project_root,
            asset_type=asset_type,
            folder_prefix=asset_dir,
            name=new_name,
            operation="duplicate",
        )
        transactional_copytree(src_folder, dst_folder)
        old_yy = dst_folder / f"{old_name}.yy"
        new_yy = dst_folder / f"{new_name}.yy"
        transactional_rename(old_yy, new_yy)

        sidecars = _rename_named_sidecars(dst_folder, asset_type, old_name, new_name)

        from .reference_scanner import plan_collision_file_renames, rewrite_json_asset_references

        yy_data = source_data
        if asset_type == "object":
            # Self-collision events are retargeted to the copy; their code files follow.
            for source_file, destination_file in plan_collision_file_renames(
                new_yy, yy_data, old_name, new_name, old_path=asset_path, new_path=rel_path
            ):
                transactional_rename(source_file, destination_file)
        rewrite_json_asset_references(
            yy_data, old_name, new_name, asset_type, old_path=asset_path, new_path=rel_path, own_asset=True
        )
        yy_data, identity_replacements = _regenerate_duplicate_identities(asset_type, yy_data)
        _rename_identity_paths(dst_folder, identity_replacements)
        save_pretty_json_gm(new_yy, yy_data)

        insert_into_resources(resources, new_name, rel_path)
        _duplicate_resource_order_entries(
            project_root,
            yyp_data,
            new_name,
            asset_path,
            rel_path,
        )
        save_pretty_json_gm(yyp_path, yyp_data)
    except Exception:
        if not transaction_is_active(project_root):
            transactional_rmtree(dst_folder, ignore_errors=True)
        raise

    validation_errors = _validate_registered_asset(
        project_root,
        rel_path,
        new_name,
        sidecars=sidecars,
        stale_names=tuple(f"{old_name}{extension}" for extension in (".yy", *_NAMED_SIDECARS.get(asset_type, ()))),
    )
    if validation_errors:
        raise JSONParseError("Duplicate validation failed: " + "; ".join(validation_errors))

    message = f"[OK] Duplicated asset -> {new_name}"
    print(_c(message, "green"))

    return AssetResult(
        success=True,
        message=message,
        warnings=[],
        asset_name=new_name,
        asset_type=asset_type,
        asset_path=rel_path,
    )


# ---------------------------------------------------------------------------
# C-2: Rename Asset
# ---------------------------------------------------------------------------


def rename_asset(project_root: Path, asset_path: str, new_name: str) -> AssetResult:
    project_root = Path(project_root).resolve()
    asset_type, src_folder, old_name = _asset_from_path(project_root, asset_path)
    new_name = _validate_asset_name(new_name)
    if asset_type == "folder":
        raise InvalidAssetTypeError("Folder resources cannot be renamed with the asset workflow.")
    asset_dir = _asset_directory(asset_type)

    require_asset_destination_available(
        project_root=project_root,
        asset_type=asset_type,
        folder_prefix=asset_dir,
        name=new_name,
        operation="rename",
    )
    dst_folder = project_root / asset_dir / new_name.lower()

    old_yy = src_folder / f"{old_name}.yy"
    yy_data = load_json_loose(old_yy)
    if not isinstance(yy_data, dict):
        raise JSONParseError(f"Could not load {old_yy} for updating")

    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if not isinstance(yyp_data, dict):
        raise JSONParseError(f"Could not load {yyp_path} for updating")
    resources = yyp_data.get("resources", [])
    source_entries = [
        entry
        for entry in resources
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), dict)
        and entry["id"].get("path") == asset_path
        and entry["id"].get("name") == old_name
    ]
    if len(source_entries) != 1:
        raise AssetNotFoundError(
            f"Expected one registered source asset '{old_name}' at '{asset_path}', found {len(source_entries)}."
        )
    if any(
        isinstance(entry, dict) and isinstance(entry.get("id"), dict) and entry["id"].get("name") == new_name
        for entry in resources
    ):
        raise AssetExistsError(f"A project resource named '{new_name}' already exists.")

    new_rel_path = f"{asset_dir}/{new_name.lower()}/{new_name}.yy"
    from .reference_scanner import preflight_asset_rename

    preflight_asset_rename(project_root, old_name, new_name, asset_type, old_path=asset_path, new_path=new_rel_path)

    # The checked destination can become stale while references are scanned.
    require_asset_destination_available(
        project_root=project_root,
        asset_type=asset_type,
        folder_prefix=asset_dir,
        name=new_name,
        operation="rename",
    )
    transactional_rename(src_folder, dst_folder)

    # Rename key files
    old_yy = dst_folder / f"{old_name}.yy"
    new_yy = dst_folder / f"{new_name}.yy"
    transactional_rename(old_yy, new_yy)

    sidecars = _rename_named_sidecars(dst_folder, asset_type, old_name, new_name)

    yy_data["name"] = new_name
    if "%Name" in yy_data:
        yy_data["%Name"] = new_name
    save_pretty_json_gm(new_yy, yy_data)

    # Update .yyp entry
    source_entry = source_entries[0]["id"]
    source_entry["name"] = new_name
    source_entry["path"] = new_rel_path
    # Move only the renamed entry; every other registration keeps its line.
    from .gm_order import RESOURCE_ORDERINGS, insert_ordered

    yyp_data["resources"].remove(source_entries[0])
    insert_ordered(yyp_data["resources"], source_entries[0], RESOURCE_ORDERINGS)
    save_pretty_json_gm(yyp_path, yyp_data)

    message = f"[OK] Renamed {old_name} -> {new_name}"
    print(_c(message, "green"))

    from .reference_scanner import comprehensive_rename_asset

    print(_c("[SCAN] Updating executable GML tokens and structured resource references...", "blue"))
    ref_success = comprehensive_rename_asset(
        project_root, old_name, new_name, asset_type, old_path=asset_path, new_path=new_rel_path
    )
    if not ref_success:
        raise JSONParseError("Rename validation failed: executable or structured stale references remain.")

    validation_errors = _validate_registered_asset(
        project_root,
        new_rel_path,
        new_name,
        sidecars=sidecars,
        stale_names=tuple(f"{old_name}{extension}" for extension in (".yy", *_NAMED_SIDECARS.get(asset_type, ()))),
    )
    if validation_errors:
        raise JSONParseError("Rename validation failed: " + "; ".join(validation_errors))

    return AssetResult(
        success=True,
        message=message,
        warnings=[],
        asset_name=new_name,
        asset_type=asset_type,
        asset_path=new_rel_path,
    )


# ---------------------------------------------------------------------------
# C-3: Delete Asset
# ---------------------------------------------------------------------------


def delete_asset(
    project_root: Path,
    asset_path: str,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> OperationResult:
    """Delete one registered asset, blocking live dependencies unless forced."""
    project_root = Path(project_root).resolve()
    asset_type, folder_path, asset_name = _asset_from_path(project_root, asset_path)

    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if not isinstance(yyp_data, dict):
        raise JSONParseError(f"Could not load {yyp_path} for updating")
    resources = yyp_data.get("resources", [])
    resource_entries = [
        entry
        for entry in resources
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), dict)
        and entry["id"].get("name") == asset_name
        and entry["id"].get("path") == asset_path
    ]
    if len(resource_entries) != 1:
        return OperationResult.fail(
            f"Delete blocked: expected one registered asset '{asset_name}' at '{asset_path}', "
            f"found {len(resource_entries)}.",
            code="asset_registration_invalid",
            error_type="validation_error",
            data={"asset_name": asset_name, "asset_type": asset_type, "asset_path": asset_path},
        )

    dependencies = _collect_incoming_dependencies(project_root, asset_name)
    if dependencies and not force:
        return OperationResult.fail(
            f"Delete blocked: {len(dependencies)} dependent asset(s) reference '{asset_name}'.",
            code="asset_has_dependencies",
            error_type="dependency_error",
            details={"dependencies": dependencies},
            data={
                "asset_name": asset_name,
                "asset_type": asset_type,
                "asset_path": asset_path,
                "blocked": True,
                "dependencies": dependencies,
                "dependency_count": len(dependencies),
                "dry_run": dry_run,
                "force": force,
            },
        )

    warnings: List[str] = []
    detached: List[str] = []
    if dependencies and force:
        try:
            detached = _detach_structural_references(project_root, asset_path, asset_name, apply=False)
        except ValidationError as exc:
            return OperationResult.fail(
                str(exc),
                code="asset_references_not_detachable",
                error_type="dependency_error",
                details={"dependencies": dependencies},
                data={"asset_name": asset_name, "asset_type": asset_type, "asset_path": asset_path},
            )
        warnings.append(
            f"Forced deletion detaches {len(detached)} structural reference(s); GML code references are left "
            "unresolved and no code was rewritten."
        )

    if dry_run:
        message = f"[dry-run] Would delete {asset_type} '{asset_name}' at {asset_path}"
        print(_c(message, "yellow"))
        return OperationResult.ok(
            message,
            warnings=warnings,
            data={
                "asset_name": asset_name,
                "asset_type": asset_type,
                "asset_path": asset_path,
                "blocked": False,
                "dependencies": dependencies,
                "dependency_count": len(dependencies),
                "detached_references": detached,
                "deleted": False,
                "dry_run": True,
                "force": force,
            },
        )

    if not folder_path.exists():
        return OperationResult.fail(
            f"Delete blocked: asset path is missing: {folder_path}",
            code="asset_files_missing",
            error_type="validation_error",
        )
    if detached:
        _detach_structural_references(project_root, asset_path, asset_name, apply=True)
    if folder_path.is_dir():
        transactional_rmtree(folder_path)
    else:
        transactional_unlink(folder_path)
    yyp_data["resources"] = [entry for entry in resources if entry is not resource_entries[0]]
    _remove_resource_order_entries(project_root, yyp_data, asset_path)
    save_pretty_json_gm(yyp_path, yyp_data)

    remaining_entries = [
        entry
        for entry in yyp_data.get("resources", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), dict)
        and (entry["id"].get("name") == asset_name or entry["id"].get("path") == asset_path)
    ]
    if folder_path.exists() or remaining_entries:
        raise JSONParseError(f"Delete validation failed for '{asset_name}'.")
    if asset_type == "room" and any(
        isinstance(entry, dict)
        and isinstance(entry.get("roomId"), dict)
        and (
            entry["roomId"].get("name") == asset_name
            or str(entry["roomId"].get("path", "")).replace("\\", "/") == asset_path
        )
        for entry in yyp_data.get("RoomOrderNodes", [])
    ):
        raise JSONParseError(f"Delete validation left a stale room-order entry for '{asset_name}'.")

    message = f"Deleted {asset_type} '{asset_name}' at {asset_path}"
    print(_c(message, "red"))
    return OperationResult.ok(
        message,
        warnings=warnings,
        data={
            "asset_name": asset_name,
            "asset_type": asset_type,
            "asset_path": asset_path,
            "blocked": False,
            "dependencies": dependencies,
            "dependency_count": len(dependencies),
            "detached_references": detached,
            "deleted": True,
            "dry_run": False,
            "force": force,
        },
    )


# Optional resource fields GameMaker serializes as null when unset.
_NULLABLE_REFERENCE_KEYS = frozenset({"spriteId", "spriteMaskId", "parentObjectId"})


def _detach_structural_references(project_root: Path, asset_path: str, asset_name: str, *, apply: bool) -> List[str]:
    """Remove or null every structural reference to a force-deleted asset.

    Optional fields become null; room instances, room sprite graphics,
    overridden properties and collision events that exist only for the target
    are removed (with their code files). Any other reference cannot be
    detached safely and raises ``ValidationError`` before anything changes.
    Returns a description of each detached reference.
    """
    from .reference_scanner import is_ignored_project_path, load_project_json

    target = asset_path.replace("\\", "/")
    target_folder = (project_root / target).parent
    detached: List[str] = []

    def is_target(reference: Any) -> bool:
        return isinstance(reference, dict) and str(reference.get("path", "")).replace("\\", "/") == target

    def removal(item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        resource_type = item.get("resourceType")
        if resource_type == "GMRInstance" and is_target(item.get("objectId")):
            return "room instance"
        if resource_type == "GMRSpriteGraphic" and is_target(item.get("spriteId")):
            return "room sprite graphic"
        if resource_type == "GMOverriddenProperty" and (
            is_target(item.get("propertyId")) or is_target(item.get("objectId"))
        ):
            return "overridden property"
        if resource_type == "GMEvent" and item.get("eventType") == 4 and is_target(item.get("collisionObjectId")):
            return "collision event"
        return None

    for yy_path in sorted(project_root.rglob("*.yy")):
        relative = yy_path.relative_to(project_root)
        if is_ignored_project_path(relative) or yy_path.parent == target_folder:
            continue
        data = load_project_json(yy_path)
        changes: List[str] = []
        removed_files: List[Path] = []
        removed_instances: set[str] = set()

        def visit(node: Any, location: str) -> None:
            if isinstance(node, list):
                kept = []
                for index, item in enumerate(node):
                    kind = removal(item)
                    if kind is None:
                        kept.append(item)
                        visit(item, f"{location}[{index}]")
                        continue
                    changes.append(f"{relative.as_posix()}{location}[{index}]: removed {kind}")
                    if kind == "room instance":
                        removed_instances.add(str(item.get("name")))
                        removed_files.append(yy_path.parent / f"InstanceCreationCode_{item.get('name')}.gml")
                    elif kind == "collision event":
                        removed_files.append(yy_path.parent / f"Collision_{asset_name}.gml")
                node[:] = kept
                return
            if not isinstance(node, dict):
                return
            for key, value in node.items():
                if is_target(value):
                    if key not in _NULLABLE_REFERENCE_KEYS:
                        raise ValidationError(
                            f"Force delete cannot detach the '{key}' reference in {relative.as_posix()}{location}; "
                            "remove that reference first."
                        )
                    node[key] = None
                    changes.append(f"{relative.as_posix()}{location}.{key}: set to null")
                else:
                    visit(value, f"{location}.{key}")

        visit(data, "")
        if removed_instances and isinstance(data, dict) and isinstance(data.get("instanceCreationOrder"), list):
            data["instanceCreationOrder"] = [
                entry
                for entry in data["instanceCreationOrder"]
                if (entry.get("name") if isinstance(entry, dict) else entry) not in removed_instances
            ]
        if not changes:
            continue
        detached.extend(changes)
        if apply:
            save_pretty_json_gm(yy_path, data)
            for code_file in removed_files:
                if code_file.is_file():
                    transactional_unlink(code_file)
    return detached


def _resolve_asset_path(project_root: Path, asset_type: str, asset_name: str) -> Optional[str]:
    """Resolve an asset type/name pair to a .yy path from the .yyp resource list."""
    from .introspection import list_assets_by_type

    assets = list_assets_by_type(project_root, asset_type_filter=asset_type, include_included_files=True)
    for asset in assets.get(asset_type, []):
        if asset.get("name") == asset_name:
            path = asset.get("path")
            if isinstance(path, str):
                return path
    return None


def _collect_incoming_dependencies(project_root: Path, asset_name: str) -> List[Dict[str, Any]]:
    """Find all incoming graph edges that point to the target asset."""
    from .introspection import build_asset_graph
    from .reference_scanner import (
        count_gml_identifier,
        count_json_resource_references,
        is_ignored_project_path,
        load_project_json,
        read_gml_source,
    )

    owners = _registered_owners(project_root)
    graph = build_asset_graph(project_root, deep=False)
    node_by_id = {node.get("id"): node for node in graph.get("nodes", []) if isinstance(node, dict)}
    directory_types = {directory: asset_type for asset_type, directory in _ASSET_DIRECTORIES.items()}

    incoming: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if edge.get("to") != asset_name:
            continue
        source_name = edge.get("from")
        if not isinstance(source_name, str) or source_name == asset_name:
            continue

        source_node = node_by_id.get(source_name, {})
        relation = str(edge.get("relation", "unknown"))
        key = (source_name, relation)
        if key not in seen:
            seen.add(key)
            incoming.append(
                {
                    "asset_name": source_name,
                    "asset_type": source_node.get("type", "unknown"),
                    "asset_path": source_node.get("path", ""),
                    "relation": relation,
                }
            )

    for gml_path in sorted(project_root.rglob("*.gml")):
        relative = gml_path.relative_to(project_root)
        if is_ignored_project_path(relative):
            continue
        # Code belongs to the registered asset whose .yy shares its directory;
        # unregistered folders are not compiled by GameMaker.
        owner = owners.get(relative.parent.as_posix())
        if owner is None:
            continue
        source_name, owner_path = owner
        if source_name == asset_name:
            continue
        source = read_gml_source(gml_path)
        if count_gml_identifier(source, asset_name) == 0:
            continue
        key = (source_name, "code_reference")
        if key in seen:
            continue
        seen.add(key)
        source_node = node_by_id.get(source_name, {})
        incoming.append(
            {
                "asset_name": source_name,
                "asset_type": source_node.get("type", directory_types.get(relative.parts[0], "unknown")),
                "asset_path": source_node.get("path", owner_path),
                "relation": "code_reference",
            }
        )

    target_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict) and node.get("id") == asset_name]
    if target_nodes:
        target_path = str(target_nodes[0].get("path", "")).replace("\\", "/")
        sources_with_dependencies = {str(item.get("asset_name", "")) for item in incoming}
        registered_paths = {path: name for name, path in owners.values()}
        for yy_path in sorted(project_root.rglob("*.yy")):
            relative = yy_path.relative_to(project_root)
            if is_ignored_project_path(relative):
                continue
            source_name = registered_paths.get(relative.as_posix())
            if source_name is None or relative.as_posix() == target_path:
                continue
            data = load_project_json(yy_path)
            if count_json_resource_references(data, target_path, asset_name) == 0:
                continue
            if source_name in sources_with_dependencies:
                continue
            source_type = directory_types.get(relative.parts[0], "unknown")
            incoming.append(
                {
                    "asset_name": source_name,
                    "asset_type": source_type,
                    "asset_path": relative.as_posix(),
                    "relation": "resource_reference",
                }
            )
            sources_with_dependencies.add(source_name)

    incoming.sort(key=lambda d: (str(d.get("asset_type", "")), str(d.get("asset_name", ""))))
    return incoming


def safe_delete_preflight(
    project_root: Path, asset_type: str, asset_name: str, *, force: bool = False
) -> Dict[str, Any]:
    """Return read-only deletion evidence suitable for a Resolve decision."""
    root = Path(project_root).resolve()
    if asset_type not in ASSET_TYPES:
        return {
            "ok": False,
            "ready": False,
            "blocked": False,
            "asset_type": asset_type,
            "asset_name": asset_name,
            "asset_path": None,
            "dependencies": [],
            "dependency_count": 0,
            "force": force,
            "error": f"Unsupported safe-delete asset type '{asset_type}'. Supported types: {', '.join(ASSET_TYPES)}.",
        }
    asset_path = _resolve_asset_path(root, asset_type, asset_name)
    if not asset_path:
        return {
            "ok": False,
            "ready": False,
            "blocked": False,
            "asset_type": asset_type,
            "asset_name": asset_name,
            "asset_path": None,
            "dependencies": [],
            "dependency_count": 0,
            "force": force,
            "error": f"Asset '{asset_name}' of type '{asset_type}' was not found.",
        }

    dependencies = _collect_incoming_dependencies(root, asset_name)
    blocked = bool(dependencies) and not force
    return {
        "ok": not blocked,
        "ready": not blocked,
        "blocked": blocked,
        "asset_type": asset_type,
        "asset_name": asset_name,
        "asset_path": asset_path,
        "dependencies": dependencies,
        "dependency_count": len(dependencies),
        "force": force,
        "resolution_required": "force" if blocked else None,
        "overwrite_supported": False,
    }


def safe_delete_asset(
    project_root: Path,
    asset_type: str,
    asset_name: str,
    *,
    force: bool = False,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Dependency-aware delete workflow.
    Defaults to dry-run and blocks apply when incoming dependencies exist unless force=True.
    """
    project_root = Path(project_root).resolve()
    preflight = safe_delete_preflight(project_root, asset_type, asset_name, force=force)
    asset_path = preflight.get("asset_path")
    if not asset_path:
        return {
            **preflight,
            "dry_run": dry_run,
            "deleted": False,
            "warnings": [],
        }

    dependencies = preflight["dependencies"]
    blocked = bool(preflight["blocked"])
    warnings: List[str] = []

    if blocked:
        warnings.append("Deletion blocked because dependent assets reference this target. Use force=True to continue.")
    elif dependencies:
        warnings.append(
            f"Force permits deletion with {len(dependencies)} unresolved dependent reference(s); no code will be rewritten."
        )

    if dry_run or blocked:
        message = (
            f"[SAFE DELETE] {'Blocked' if blocked else 'Dry-run'} for {asset_type} '{asset_name}' "
            f"({len(dependencies)} dependent reference(s))."
        )
        print(_c(message, "yellow"))
        return {
            "ok": not blocked,
            "blocked": blocked,
            "asset_type": asset_type,
            "asset_name": asset_name,
            "asset_path": asset_path,
            "dry_run": dry_run,
            "force": force,
            "dependencies": dependencies,
            "dependency_count": len(dependencies),
            "deleted": False,
            "warnings": warnings,
            "message": message,
            "preflight": preflight,
        }

    # A resolved apply must re-scan immediately before mutation.  This avoids
    # acting on dependency evidence that became stale after the initial probe.
    final_preflight = safe_delete_preflight(project_root, asset_type, asset_name, force=force)
    if not final_preflight.get("asset_path") or final_preflight.get("blocked"):
        final_dependencies = final_preflight.get("dependencies", [])
        final_blocked = bool(final_preflight.get("blocked"))
        return {
            **final_preflight,
            "ok": False,
            "blocked": final_blocked,
            "dry_run": False,
            "deleted": False,
            "warnings": (
                ["Deletion blocked because dependent assets reference this target. Use force=True to continue."]
                if final_blocked
                else []
            ),
            "message": (
                f"[SAFE DELETE] Blocked for {asset_type} '{asset_name}' "
                f"({len(final_dependencies)} dependent reference(s))."
                if final_blocked
                else str(final_preflight.get("error") or "Safe delete preflight is no longer valid.")
            ),
            "preflight": preflight,
            "revalidation": final_preflight,
        }

    delete_result = delete_asset(project_root, asset_path, dry_run=False, force=force)
    warnings.extend(delete_result.warnings)

    return {
        "ok": bool(delete_result.success),
        "blocked": False,
        "asset_type": asset_type,
        "asset_name": asset_name,
        "asset_path": asset_path,
        "dry_run": False,
        "force": force,
        "dependencies": final_preflight["dependencies"],
        "dependency_count": final_preflight["dependency_count"],
        "deleted": bool(delete_result.success),
        "warnings": warnings,
        "message": delete_result.message,
        "preflight": preflight,
        "revalidation": final_preflight,
        "final_validation": {
            "asset_absent": _resolve_asset_path(project_root, asset_type, asset_name) is None,
            "deleted": bool(delete_result.success),
        },
    }


# ---------------------------------------------------------------------------
# C-4: Swap Sprite PNG
# ---------------------------------------------------------------------------


def swap_sprite_png(
    project_root: Path, sprite_asset_path: str, png_source: Path, frame_index: int = 0
) -> OperationResult:
    """Replace a sprite frame's PNG source.

    Args:
        project_root: Project root directory
        sprite_asset_path: Sprite asset path (e.g., "sprites/spr_player/spr_player.yy")
        png_source: Path to new PNG file
        frame_index: Frame index to replace (0-indexed, default: 0 for backwards compat)
    """
    project_root = Path(project_root)
    asset_type, folder_path, sprite_name = _asset_from_path(project_root, sprite_asset_path)
    if asset_type != "sprite":
        raise InvalidAssetTypeError("swap_sprite_png only valid for sprites")

    from .sprite_frames import require_modern_sprite_format, require_png_matches_sprite, sprite_layer_ids

    yy_path = folder_path / f"{sprite_name}.yy"
    yy_data = load_json_loose(yy_path)
    if yy_data is None:
        raise JSONParseError(f"Could not load {yy_path}")
    require_modern_sprite_format(yy_data, yy_path)
    layer_uuids = sprite_layer_ids(yy_data)
    if len(layer_uuids) > 1:
        raise ValidationError(
            f"Sprite '{sprite_name}' has {len(layer_uuids)} image layers; one PNG cannot replace a layered frame. "
            "Edit the layers in GameMaker."
        )

    # Validate frame_index
    frame_count = len(yy_data["frames"])
    if frame_index < 0 or frame_index >= frame_count:
        raise ValueError(
            f"Invalid frame_index {frame_index}: sprite '{sprite_name}' has "
            f"{frame_count} frame(s) (valid: 0-{frame_count - 1})"
        )

    frame_uuid = validate_resource_name(yy_data["frames"][frame_index]["name"], "sprite frame")
    layer_uuid = layer_uuids[0]
    target_png = project_child_path(folder_path, f"{frame_uuid}.png", project_root=project_root)
    layer_png = project_child_path(folder_path, "layers", frame_uuid, f"{layer_uuid}.png", project_root=project_root)

    png_source = Path(png_source)
    if not png_source.is_absolute():
        png_source = (project_root / png_source).resolve()

    if not png_source.exists():
        raise FileNotFoundError(f"PNG source not found: {png_source}")

    # If the user accidentally points at the current sprite frame PNG, treat as a no-op.
    try:
        if png_source.resolve() == target_png.resolve():
            message = (
                f"[OK] Sprite image for {sprite_name} frame {frame_index} already matches the provided PNG (no-op)"
            )
            print(_c(message, "green"))
            return OperationResult(success=True, message=message)
    except Exception:
        # If resolve fails for any reason, fall back to attempting the copy.
        pass
    require_png_matches_sprite(png_source, yy_data)

    # Windows can lock files; use a temp file + replace, with small retries.
    tmp_png = project_child_path(folder_path, f"{frame_uuid}.png.swap_tmp", project_root=project_root)
    last_err: Exception | None = None
    for attempt in range(1, 6):
        try:
            transactional_copy2(png_source, tmp_png)
            try:
                transactional_replace(tmp_png, target_png)
            finally:
                if tmp_png.exists():
                    # Best-effort cleanup
                    try:
                        transactional_unlink(tmp_png)
                    except Exception:
                        pass

            # Also update the layer PNG if it exists
            if layer_png.parent.exists():
                transactional_copy2(png_source, layer_png)

            frame_msg = f" frame {frame_index}" if frame_count > 1 else ""
            message = f"[OK] Replaced sprite image for {sprite_name}{frame_msg}"
            print(_c(message, "green"))
            return OperationResult(success=True, message=message)
        except PermissionError as e:
            last_err = e
            time.sleep(0.1 * attempt)
        except Exception as e:
            last_err = e
            break

    raise PermissionError(
        f"Could not replace sprite PNG for {sprite_name}. Target may be locked by another process. "
        f"Close GameMaker/Explorer preview and retry. Last error: {last_err}"
    )


# ---------------------------------------------------------------------------
# C-5: Project Linter
# ---------------------------------------------------------------------------


def lint_project(project_root: Path) -> MaintenanceResult:
    """Check for common project issues."""
    project_root = Path(project_root)
    yyp_path = find_yyp(project_root)
    yyp_data = load_json_loose(yyp_path)
    if yyp_data is None:
        raise JSONParseError(f"Could not load {yyp_path}")

    problems: List[str] = []

    resources: List[Tuple[str, str]] = []
    for index, res in enumerate(yyp_data.get("resources", [])):
        identity = res.get("id") if isinstance(res, dict) else None
        name = identity.get("name") if isinstance(identity, dict) else None
        path = identity.get("path") if isinstance(identity, dict) else None
        if not isinstance(name, str) or not name or not isinstance(path, str) or not path:
            problems.append(f"Malformed .yyp resource entry {index}: expected id.name and id.path, got {res!r}")
            continue
        resources.append((name, path))

    # 1. Resource order
    sorted_names = sorted(name for name, _path in resources)
    actual_names = [name for name, _path in resources]
    if sorted_names != actual_names:
        problems.append("Resources not alphabetically ordered in .yyp")

    # 2. Missing files
    for _name, path in resources:
        p = project_root / path
        if not p.exists():
            problems.append(f"Missing file: {p}")

    # 3. Extra folders not in .yyp (only scripts/objects/sprites/rooms)
    resource_paths = {path for _name, path in resources}
    for top in ["scripts", "objects", "sprites", "rooms"]:
        top_dir = project_root / top
        if top_dir.exists():
            for yy in top_dir.rglob("*.yy"):
                rel = yy.relative_to(project_root).as_posix()
                if rel not in resource_paths:
                    problems.append(f"Orphan .yy file not in .yyp: {rel}")

    # 4. JSON validity of each .yy
    for yy in project_root.rglob("*.yy"):
        try:
            if load_json_loose(yy) is None:
                problems.append(f"Invalid JSON: {yy}")
        except Exception as e:
            problems.append(f"Invalid JSON: {yy} - {e}")

    # ------------------------------------------------------------------
    # Report
    if not problems:
        message = "[OK] Project looks good!"
        print(_c(message, "green"))
        return MaintenanceResult(success=True, message=message, issues_found=0, issues_fixed=0)

    for p in problems:
        print(_c("[ERROR] " + p, "red"))

    error_msg = f"Found {len(problems)} problem(s)"
    print(_c(error_msg, "red"))

    return MaintenanceResult(
        success=False, message=error_msg, issues_found=len(problems), issues_fixed=0, details=problems
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _patch_gml_stub(gml_file: Path, old_name: str, new_name: str) -> None:
    """Rename an executable script identifier without touching prose or strings."""
    from .reference_scanner import read_gml_source, rewrite_gml_asset_identifiers
    from .utils import atomic_write_text

    text = read_gml_source(gml_file)
    patched, replacements = rewrite_gml_asset_identifiers(text, {old_name: new_name})
    if replacements:
        atomic_write_text(gml_file, patched)


if __name__ == "__main__":
    print("This module is intended to be imported, not run directly. Use cli_ext.py instead.")
