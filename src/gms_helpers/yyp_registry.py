"""Direct, minimal-diff edits to the ``.yyp`` registries.

Everything here changes only the lines that belong to the entries being added or removed:
existing registrations keep their position and the file keeps GameMaker's own layout (see
``gm_json`` and ``gm_order``). That is what makes these operations safe when several agents
or people are editing the same project.

The functions are plain project edits. Callers that need atomicity run them inside a
``GameMakerProjectTransaction`` (the MCP server does this for every mutating tool).
"""

from __future__ import annotations

import copy
import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from . import gm_json
from .exceptions import ValidationError
from .gm_order import (
    FOLDER_ORDERINGS,
    INCLUDED_FILE_ORDERINGS,
    RESOURCE_ORDERINGS,
    detect_ordering,
    insert_ordered,
)
from .project_validation import ASSET_RESOURCE_TYPES, safe_project_path
from .utils import find_yyp, load_json_loose, save_json

INCLUDED_PREFIX = "included:"


# ----------------------------------------------------------------------
# Loading / saving
# ----------------------------------------------------------------------
def load_yyp(project_root: str | Path) -> tuple[Path, dict[str, Any]]:
    root = Path(project_root).resolve()
    yyp_path = find_yyp(root)
    data = load_json_loose(yyp_path)
    if not isinstance(data, dict):
        raise ValidationError(
            f"{yyp_path.name} is not valid GameMaker JSON. Run gm_maintenance_validate_json to find the "
            "syntax error (often an unresolved merge conflict) before editing registrations."
        )
    for key in ("resources", "Folders", "IncludedFiles"):
        if key in data and not isinstance(data[key], list):
            raise ValidationError(f"{yyp_path.name}: '{key}' must be an array.")
    return yyp_path, data


def _save_yyp(yyp_path: Path, data: dict[str, Any]) -> None:
    save_json(data, str(yyp_path))


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").strip().strip("/")


def _resource_ref(entry: Any) -> dict[str, Any] | None:
    ref = entry.get("id") if isinstance(entry, dict) else None
    return ref if isinstance(ref, dict) and isinstance(ref.get("path"), str) else None


def _included_key(entry: Any) -> str | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        return None
    return f"{_norm(str(entry.get('filePath', '')))}/{entry['name']}"


def _asset_path_parts(asset_path: str) -> tuple[str, str]:
    """Validate ``<kind>/<name>/<name>.yy`` and return (kind, name)."""
    normalized = _norm(asset_path)
    parts = normalized.split("/")
    if len(parts) != 3 or not parts[2].endswith(".yy") or parts[0] not in ASSET_RESOURCE_TYPES:
        kinds = ", ".join(sorted(ASSET_RESOURCE_TYPES))
        raise ValidationError(
            f"'{asset_path}' is not an asset path. Expected <kind>/<folder>/<name>.yy relative to the folder "
            f"containing the .yyp (for example scripts/my_script/my_script.yy), where <kind> is one of: {kinds}."
        )
    return parts[0], parts[2][: -len(".yy")]


# ----------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------
def register_assets(project_root: str | Path, asset_paths: Iterable[str]) -> dict[str, Any]:
    """Register existing asset ``.yy`` files in the project.

    Use this after creating an asset by copying another asset's files. The ``.yy`` must
    exist and its logical parent folder must already be registered.
    """
    root = Path(project_root).resolve()
    yyp_path, data = load_yyp(root)
    resources = data.setdefault("resources", [])
    folders = {_norm(str(f.get("folderPath", ""))) for f in data.get("Folders", []) if isinstance(f, dict)}
    registered: list[str] = []
    unchanged: list[str] = []
    for raw in asset_paths:
        path = _norm(raw)
        _kind, name = _asset_path_parts(path)
        target = safe_project_path(root, path)
        if target is None or not target.is_file():
            raise ValidationError(
                f"Cannot register '{path}': the file does not exist. Create the asset files first "
                "(gm_create_* tools do both steps), then register."
            )
        asset = load_json_loose(target)
        if not isinstance(asset, dict):
            raise ValidationError(f"Cannot register '{path}': it is not valid GameMaker JSON.")
        if asset.get("name") != name:
            raise ValidationError(
                f"Cannot register '{path}': the file is named '{name}.yy' but its \"name\" is "
                f"'{asset.get('name')}'. A copied asset must have name and %Name changed to match its file."
            )
        parent = asset.get("parent") if isinstance(asset.get("parent"), dict) else {}
        parent_path = _norm(str(parent.get("path", "")))
        if parent_path != yyp_path.name and parent_path not in folders:
            raise ValidationError(
                f"Cannot register '{path}': its parent folder '{parent_path}' is not in the project. "
                "Create it with gm_create_folder (parents first) or set the asset's parent to an existing "
                "folder; gm_list_assets shows the folders in use."
            )
        existing = [entry for entry in resources if (_resource_ref(entry) or {}).get("name") == name]
        if existing and all(_norm(_resource_ref(entry)["path"]) == path for entry in existing):
            unchanged.append(path)
            continue
        for entry in existing:
            resources.remove(entry)
        insert_ordered(resources, {"id": {"name": name, "path": path}}, RESOURCE_ORDERINGS)
        registered.append(path)
    if registered:
        _save_yyp(yyp_path, data)
    return {"ok": True, "registered": registered, "already_registered": unchanged, "yyp": yyp_path.name}


def unregister_assets(project_root: str | Path, asset_paths: Iterable[str]) -> dict[str, Any]:
    """Remove registrations (and their asset-browser order entries). Files stay on disk."""
    root = Path(project_root).resolve()
    yyp_path, data = load_yyp(root)
    wanted = {_norm(path) for path in asset_paths}
    for path in wanted:
        _asset_path_parts(path)
    resources = data.get("resources", [])
    kept = [entry for entry in resources if _norm((_resource_ref(entry) or {}).get("path", "")) not in wanted]
    removed = sorted(
        _norm(_resource_ref(entry)["path"])
        for entry in resources
        if _norm((_resource_ref(entry) or {}).get("path", "")) in wanted
    )
    if removed:
        data["resources"] = kept
        _save_yyp(yyp_path, data)
        _drop_resource_order_entries(root, yyp_path, wanted)
    return {
        "ok": True,
        "unregistered": removed,
        "not_registered": sorted(wanted - set(removed)),
        "yyp": yyp_path.name,
    }


def _drop_resource_order_entries(root: Path, yyp_path: Path, paths: set[str]) -> None:
    order_path = yyp_path.with_suffix(".resource_order")
    if not order_path.is_file():
        return
    order = load_json_loose(order_path)
    if not isinstance(order, dict):
        return
    changed = False
    for key, entries in order.items():
        if isinstance(entries, list):
            kept = [e for e in entries if not (isinstance(e, dict) and _norm(str(e.get("path", ""))) in paths)]
            if len(kept) != len(entries):
                order[key] = kept
                changed = True
    if changed:
        save_json(order, str(order_path))


# ----------------------------------------------------------------------
# Folders
# ----------------------------------------------------------------------
def move_asset(project_root: str | Path, asset_path: str, parent_path: str) -> dict[str, Any]:
    """Move an asset to another asset-browser folder (edits only its ``parent``)."""
    root = Path(project_root).resolve()
    yyp_path, data = load_yyp(root)
    path = _norm(asset_path)
    _asset_path_parts(path)
    target = safe_project_path(root, path)
    asset = load_json_loose(target) if target is not None and target.is_file() else None
    if not isinstance(asset, dict):
        raise ValidationError(f"Cannot move '{path}': the asset file does not exist or is not valid JSON.")
    wanted = _norm(parent_path)
    folder = next(
        (
            f
            for f in data.get("Folders", [])
            if isinstance(f, dict) and _norm(str(f.get("folderPath", ""))) == wanted
        ),
        None,
    )
    if folder is None:
        raise ValidationError(
            f"Cannot move '{path}': folder '{wanted}' is not in the project. Folder paths look like "
            "folders/Parent/Child.yy; create it with gm_create_folder first."
        )
    previous = asset.get("parent") if isinstance(asset.get("parent"), dict) else {}
    if _norm(str(previous.get("path", ""))) == wanted and previous.get("name") == folder.get("name"):
        return {"ok": True, "moved": False, "asset": path, "parent": wanted, "message": "Already in that folder."}
    asset["parent"] = {"name": folder.get("name"), "path": wanted}
    save_json(asset, str(target))
    return {"ok": True, "moved": True, "asset": path, "parent": wanted, "previous_parent": previous.get("path")}


# ----------------------------------------------------------------------
# Included files
# ----------------------------------------------------------------------
def _split_included(path: str) -> tuple[str, str]:
    normalized = _norm(path)
    if not normalized.startswith("datafiles/") or normalized.endswith("/"):
        raise ValidationError(
            f"'{path}' is not an included file. Included files live under datafiles/, for example "
            "datafiles/data/items/sword.json."
        )
    directory, _, name = normalized.rpartition("/")
    return directory, name


def _included_template(data: dict[str, Any]) -> dict[str, Any]:
    for entry in data.get("IncludedFiles", []):
        if isinstance(entry, dict) and "name" in entry and "filePath" in entry:
            template = copy.deepcopy(entry)
            template.pop("ConfigValues", None)
            return template
    return {
        "$GMIncludedFile": "",
        "%Name": "",
        "CopyToMask": -1,
        "filePath": "",
        "name": "",
        "resourceType": "GMIncludedFile",
        "resourceVersion": "2.0",
    }


def list_included_files(project_root: str | Path, prefix: str = "") -> dict[str, Any]:
    root = Path(project_root).resolve()
    _yyp_path, data = load_yyp(root)
    wanted = _norm(prefix)
    files = sorted(
        key
        for key in (_included_key(entry) for entry in data.get("IncludedFiles", []))
        if key and (not wanted or key.startswith(wanted))
    )
    return {"ok": True, "count": len(files), "included_files": files}


def add_included_files(
    project_root: str | Path, paths: Iterable[str], *, copy_to_mask: int | None = None
) -> dict[str, Any]:
    """Register files under ``datafiles/``. A directory registers every file below it."""
    root = Path(project_root).resolve()
    yyp_path, data = load_yyp(root)
    included = data.setdefault("IncludedFiles", [])
    present = {_included_key(entry) for entry in included}
    template = _included_template(data)
    added: list[str] = []
    unchanged: list[str] = []
    expanded: list[str] = []
    for raw in paths:
        normalized = _norm(raw)
        target = safe_project_path(root, normalized)
        if target is None or not normalized.startswith("datafiles"):
            raise ValidationError(f"'{raw}' is not under datafiles/ in this project.")
        if target.is_dir():
            expanded.extend(
                child.relative_to(root).as_posix()
                for child in sorted(target.rglob("*"))
                if child.is_file() and not child.name.startswith(".")
            )
        elif target.is_file():
            expanded.append(normalized)
        else:
            raise ValidationError(
                f"Cannot include '{raw}': the file does not exist. Write the file under datafiles/ first."
            )
    for path in expanded:
        directory, name = _split_included(path)
        key = f"{directory}/{name}"
        if key in present:
            unchanged.append(key)
            continue
        entry = copy.deepcopy(template)
        entry["%Name"] = name
        entry["name"] = name
        entry["filePath"] = directory
        if copy_to_mask is not None:
            entry["CopyToMask"] = copy_to_mask
        insert_ordered(included, entry, INCLUDED_FILE_ORDERINGS)
        present.add(key)
        added.append(key)
    if added:
        _save_yyp(yyp_path, data)
    return {"ok": True, "added": added, "already_included": unchanged, "yyp": yyp_path.name}


def remove_included_files(project_root: str | Path, paths: Iterable[str]) -> dict[str, Any]:
    """Unregister included files (a directory path removes everything below it). Files stay on disk."""
    root = Path(project_root).resolve()
    yyp_path, data = load_yyp(root)
    wanted = [_norm(path) for path in paths]
    included = data.get("IncludedFiles", [])

    def matches(key: str | None) -> bool:
        return key is not None and any(key == path or key.startswith(path + "/") for path in wanted)

    removed = sorted(key for key in (_included_key(entry) for entry in included) if matches(key))
    if removed:
        data["IncludedFiles"] = [entry for entry in included if not matches(_included_key(entry))]
        _save_yyp(yyp_path, data)
    return {"ok": True, "removed": removed, "yyp": yyp_path.name}


# ----------------------------------------------------------------------
# Configurations and audio groups
# ----------------------------------------------------------------------
def list_configs(project_root: str | Path) -> dict[str, Any]:
    _yyp_path, data = load_yyp(project_root)

    def walk(node: Any, prefix: str = "") -> list[str]:
        if not isinstance(node, dict):
            return []
        name = f"{prefix}{node.get('name', '')}"
        names = [name]
        for child in node.get("children", []) or []:
            names.extend(walk(child, name + "/"))
        return names

    return {"ok": True, "configs": walk(data.get("configs", {}))}


def add_config(project_root: str | Path, name: str, parent: str = "Default") -> dict[str, Any]:
    """Add a build configuration under ``parent`` (the root configuration is ``Default``)."""
    yyp_path, data = load_yyp(project_root)
    if not name or any(character in name for character in '/\\"'):
        raise ValidationError("Configuration names cannot be empty or contain slashes or quotes.")

    def find(node: Any, wanted: str) -> dict[str, Any] | None:
        if not isinstance(node, dict):
            return None
        if node.get("name") == wanted:
            return node
        for child in node.get("children", []) or []:
            hit = find(child, wanted)
            if hit is not None:
                return hit
        return None

    configs = data.setdefault("configs", {"children": [], "name": "Default"})
    if find(configs, name) is not None:
        return {"ok": True, "added": False, "config": name, "message": "Configuration already exists."}
    target = find(configs, parent)
    if target is None:
        raise ValidationError(
            f"Parent configuration '{parent}' does not exist. Existing: "
            f"{', '.join(list_configs(project_root)['configs'])}."
        )
    target.setdefault("children", []).append({"children": [], "name": name})
    _save_yyp(yyp_path, data)
    return {"ok": True, "added": True, "config": name, "parent": parent, "yyp": yyp_path.name}


def list_audio_groups(project_root: str | Path) -> dict[str, Any]:
    _yyp_path, data = load_yyp(project_root)
    groups = [g for g in data.get("AudioGroups", []) if isinstance(g, dict)]
    return {"ok": True, "count": len(groups), "audio_groups": groups}


def add_audio_group(project_root: str | Path, name: str) -> dict[str, Any]:
    """Add an audio group (a copy of the first existing group's settings under a new name)."""
    yyp_path, data = load_yyp(project_root)
    if not name or not name.replace("_", "").isalnum():
        raise ValidationError("Audio group names may contain only letters, digits and underscores.")
    groups = data.setdefault("AudioGroups", [])
    if any(isinstance(group, dict) and group.get("name") == name for group in groups):
        return {"ok": True, "added": False, "audio_group": name, "message": "Audio group already exists."}
    template = next((copy.deepcopy(group) for group in groups if isinstance(group, dict)), None) or {
        "$GMAudioGroup": "v1",
        "%Name": "",
        "exportDir": "",
        "name": "",
        "resourceType": "GMAudioGroup",
        "resourceVersion": "2.0",
        "targets": -1,
    }
    template["name"] = name
    if "%Name" in template:
        template["%Name"] = name
    groups.append(template)
    _save_yyp(yyp_path, data)
    return {"ok": True, "added": True, "audio_group": name, "yyp": yyp_path.name}


# ----------------------------------------------------------------------
# Integrity check
# ----------------------------------------------------------------------
def check_registry(project_root: str | Path, *, allow_root_assets: Iterable[str] = ()) -> dict[str, Any]:
    """Read-only integrity report for the ``.yyp`` registries.

    Problems are things that break the IDE or Igor; warnings are tolerated by GameMaker
    but usually mean an edit was left half done.
    """
    root = Path(project_root).resolve()
    yyp_path, data = load_yyp(root)
    problems: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def problem(kind: str, target: str, message: str, fix: str) -> None:
        problems.append({"kind": kind, "target": target, "message": message, "fix": fix})

    def warning(kind: str, target: str, message: str, fix: str) -> None:
        warnings.append({"kind": kind, "target": target, "message": message, "fix": fix})

    allowed_root = list(allow_root_assets)
    folders: dict[str, str] = {}
    for folder in data.get("Folders", []):
        if not isinstance(folder, dict) or not isinstance(folder.get("folderPath"), str):
            problem("malformed_folder", str(folder)[:80], "Folder entry is malformed.", "Remove or repair the entry.")
            continue
        path = _norm(folder["folderPath"])
        if path in folders:
            problem("duplicate_folder", path, "Folder is registered twice.", "Delete one of the two entries.")
        folders[path] = str(folder.get("name", ""))
    for path in folders:
        parent = PurePosixPath(path).parent.as_posix()
        if parent != "folders" and parent + ".yy" not in folders:
            problem(
                "missing_parent_folder",
                path,
                f"Enclosing folder '{parent}.yy' is not registered.",
                "Create the parent with gm_create_folder.",
            )

    names: dict[str, str] = {}
    paths: set[str] = set()
    registered_lower: set[str] = set()
    for entry in data.get("resources", []):
        ref = _resource_ref(entry)
        if ref is None or not isinstance(ref.get("name"), str):
            problem("malformed_resource", str(entry)[:80], "Resource entry is malformed.", "Remove or repair it.")
            continue
        name, path = ref["name"], _norm(ref["path"])
        if name.lower() in names or path.lower() in registered_lower:
            problem(
                "duplicate_resource",
                path,
                f"'{name}' is registered more than once.",
                "Run gm_maintenance_dedupe_resources.",
            )
        names[name.lower()] = path
        paths.add(path)
        registered_lower.add(path.lower())
        target = safe_project_path(root, path)
        if target is None or not target.is_file():
            problem(
                "missing_on_disk",
                path,
                "Registered but the .yy file does not exist.",
                "Restore the asset files, or remove the registration with gm_yyp_unregister.",
            )
            continue
        asset = load_json_loose(target)
        if not isinstance(asset, dict):
            problem("invalid_json", path, "The .yy file is not valid GameMaker JSON.", "Repair the file.")
            continue
        if asset.get("name") != name:
            problem(
                "name_mismatch",
                path,
                f"Registered as '{name}' but the file says '{asset.get('name')}'.",
                "Make name and %Name in the .yy match the file name.",
            )
        parent = asset.get("parent") if isinstance(asset.get("parent"), dict) else {}
        parent_path = _norm(str(parent.get("path", "")))
        if parent_path == yyp_path.name:
            if not any(fnmatch.fnmatch(name, pattern) for pattern in allowed_root):
                warning(
                    "root_asset",
                    path,
                    "Asset sits at the project root instead of in an asset-browser folder.",
                    "Move it with gm_asset_move.",
                )
        elif parent_path not in folders:
            problem(
                "unregistered_parent",
                path,
                f"Parent folder '{parent_path}' is not registered.",
                "Create the folder with gm_create_folder or move the asset with gm_asset_move.",
            )
        elif parent.get("name") != folders[parent_path]:
            warning(
                "parent_name_mismatch",
                path,
                f"parent.name is '{parent.get('name')}' but the folder is called '{folders[parent_path]}'.",
                "Run gm_asset_move with the same folder to rewrite the parent reference.",
            )

    for kind in sorted(ASSET_RESOURCE_TYPES):
        directory = root / kind
        if not directory.is_dir():
            continue
        for child in sorted(directory.iterdir()):
            candidate = child / f"{child.name}.yy"
            if not child.is_dir():
                continue
            yy_files = [candidate] if candidate.is_file() else sorted(child.glob("*.yy"))
            for yy_file in yy_files[:1]:
                relative = yy_file.relative_to(root).as_posix()
                if relative.lower() not in registered_lower:
                    problem(
                        "unregistered_on_disk",
                        relative,
                        "Asset exists on disk but is not registered, so GameMaker ignores it.",
                        "Register it with gm_yyp_register, or delete the folder if it is a leftover.",
                    )

    included_seen: set[str] = set()
    for entry in data.get("IncludedFiles", []):
        key = _included_key(entry)
        if key is None:
            problem("malformed_included_file", str(entry)[:80], "Included-file entry is malformed.", "Repair it.")
            continue
        if key.lower() in included_seen:
            problem("duplicate_included_file", key, "Included file is registered twice.", "Delete one entry.")
        included_seen.add(key.lower())
        target = safe_project_path(root, key)
        if target is None or not target.is_file():
            problem(
                "included_file_missing",
                key,
                "Registered included file does not exist on disk.",
                "Restore the file or remove it with gm_included_file_remove.",
            )
    datafiles = root / "datafiles"
    if datafiles.is_dir():
        for child in sorted(datafiles.rglob("*")):
            if child.is_file() and not child.name.startswith("."):
                relative = child.relative_to(root).as_posix()
                if relative.lower() not in included_seen:
                    warning(
                        "included_file_unregistered",
                        relative,
                        "File under datafiles/ is not registered, so it is not shipped with the game.",
                        "Register it with gm_included_file_add.",
                    )

    ordering: dict[str, str | None] = {}
    for label, entries, candidates in (
        ("resources", [e for e in data.get("resources", []) if _resource_ref(e)], RESOURCE_ORDERINGS),
        ("Folders", [f for f in data.get("Folders", []) if isinstance(f, dict) and "folderPath" in f], FOLDER_ORDERINGS),
        (
            "IncludedFiles",
            [e for e in data.get("IncludedFiles", []) if _included_key(e)],
            INCLUDED_FILE_ORDERINGS,
        ),
    ):
        rule = detect_ordering(entries, candidates)
        ordering[label] = rule[0] if rule else None
        if rule is None and len(entries) > 1:
            _label, field, key = candidates[0]
            first = next(
                (field(b) for a, b in zip(entries, entries[1:]) if key(field(a)) > key(field(b))),
                "",
            )
            warning(
                "unordered",
                label,
                f"{label} is not in GameMaker's order (first entry out of place: {first}). Igor's project "
                "loader in runtime 2026 can crash on a mis-ordered list.",
                "Run gm_yyp_normalize_order to restore the IDE's ordering.",
            )

    native = gm_json.is_native_layout(yyp_path.read_text(encoding="utf-8"))
    if not native:
        warning(
            "non_native_layout",
            yyp_path.name,
            "The .yyp is not in GameMaker's own layout, so every tool that rewrites it produces a full-file diff.",
            "Open and save the project in the GameMaker IDE, or run gm_yyp_normalize_order.",
        )

    return {
        "ok": not problems,
        "yyp": yyp_path.name,
        "problem_count": len(problems),
        "warning_count": len(warnings),
        "problems": problems,
        "warnings": warnings,
        "ordering": ordering,
        "native_layout": native,
        "counts": {
            "resources": len(data.get("resources", [])),
            "folders": len(folders),
            "included_files": len(data.get("IncludedFiles", [])),
        },
    }


def normalize_order(project_root: str | Path) -> dict[str, Any]:
    """Re-sort the three registries into the GameMaker 2026 IDE order and native layout.

    This rewrites many lines once; use it to repair a file a different tool reordered.
    """
    from .gm_order import ide_2026_key

    yyp_path, data = load_yyp(project_root)
    before = yyp_path.read_text(encoding="utf-8")
    if isinstance(data.get("resources"), list):
        data["resources"].sort(key=lambda e: ide_2026_key(_norm((_resource_ref(e) or {}).get("path", ""))))
    if isinstance(data.get("Folders"), list):
        data["Folders"].sort(key=lambda f: ide_2026_key(_norm(str(f.get("folderPath", "")))) if isinstance(f, dict) else ide_2026_key(""))
    if isinstance(data.get("IncludedFiles"), list):
        data["IncludedFiles"].sort(key=lambda e: ide_2026_key(_included_key(e) or ""))
    from .utils import atomic_write_text

    layout = gm_json.detect_layout(before) or gm_json.Layout(newline=gm_json.detect_newline(before))
    after = gm_json.dumps(data, layout)
    if after != before:
        atomic_write_text(yyp_path, after)
    changed = sum(1 for a, b in zip(before.splitlines(), after.splitlines()) if a != b) + abs(
        len(before.splitlines()) - len(after.splitlines())
    )
    return {"ok": True, "changed": after != before, "changed_lines": changed, "yyp": yyp_path.name}


# ----------------------------------------------------------------------
# "Base revision plus named registrations" (isolated builds and partial commits)
# ----------------------------------------------------------------------
def compose_yyp(base_text: str, working_text: str, entries: Iterable[str]) -> str:
    """Return ``base_text`` with only the named registrations taken from ``working_text``.

    ``entries`` are asset paths (``scripts/foo/foo.yy``), folder paths (``folders/A/B.yy``)
    and included files (``included:datafiles/data/foo.json``). An entry present in the
    working copy is added or replaced; an entry absent from it is removed. Everything else
    in the result is exactly the base revision, so other people's uncommitted
    registrations never leak into a build or a commit.
    """
    base = gm_json.loads(base_text)
    work = gm_json.loads(working_text)
    if not isinstance(base, dict) or not isinstance(work, dict):
        raise ValidationError("Both project files must be GameMaker JSON objects.")
    base_resources = base.setdefault("resources", [])
    base_folders = base.setdefault("Folders", [])
    base_included = base.setdefault("IncludedFiles", [])
    work_resources = {_norm(_resource_ref(e)["path"]): e for e in work.get("resources", []) if _resource_ref(e)}
    work_folders = {
        _norm(str(f.get("folderPath", ""))): f for f in work.get("Folders", []) if isinstance(f, dict)
    }
    work_included = {key: e for e in work.get("IncludedFiles", []) if (key := _included_key(e))}

    for raw in entries:
        entry = str(raw).strip()
        if not entry:
            continue
        if entry.startswith(INCLUDED_PREFIX):
            key = _norm(entry[len(INCLUDED_PREFIX) :])
            base_included[:] = [e for e in base_included if _included_key(e) != key]
            if key in work_included:
                insert_ordered(base_included, copy.deepcopy(work_included[key]), INCLUDED_FILE_ORDERINGS)
        elif _norm(entry).startswith("folders/"):
            key = _norm(entry)
            base_folders[:] = [f for f in base_folders if _norm(str(f.get("folderPath", ""))) != key]
            if key in work_folders:
                insert_ordered(base_folders, copy.deepcopy(work_folders[key]), FOLDER_ORDERINGS)
        else:
            key = _norm(entry)
            _asset_path_parts(key)
            name = PurePosixPath(key).stem
            base_resources[:] = [
                e
                for e in base_resources
                if _norm((_resource_ref(e) or {}).get("path", "")) != key and (_resource_ref(e) or {}).get("name") != name
            ]
            if key in work_resources:
                insert_ordered(base_resources, copy.deepcopy(work_resources[key]), RESOURCE_ORDERINGS)

    layout = gm_json.detect_layout(base_text)
    if layout is None:
        layout = gm_json.detect_layout(working_text) or gm_json.Layout(newline=gm_json.detect_newline(base_text))
    return gm_json.dumps(base, layout)


def derive_yyp_entries(project_root: str | Path, base_text: str, changed_paths: Iterable[str]) -> list[str]:
    """Work out which registrations belong to a set of changed project-relative paths.

    Used when the caller isolates "these files" without spelling out registrations: every
    asset whose folder is touched, every touched included file, and any asset-browser
    folder those assets need that the base revision does not have yet.
    """
    root = Path(project_root).resolve()
    _yyp_path, work = load_yyp(root)
    base = gm_json.loads(base_text)
    base_folders = {
        _norm(str(f.get("folderPath", ""))) for f in base.get("Folders", []) if isinstance(f, dict)
    }
    work_folders = {
        _norm(str(f.get("folderPath", ""))) for f in work.get("Folders", []) if isinstance(f, dict)
    }
    work_resources = {
        _norm(_resource_ref(e)["path"]) for e in work.get("resources", []) if _resource_ref(e)
    }
    base_resources = {
        _norm(_resource_ref(e)["path"]) for e in base.get("resources", []) if _resource_ref(e)
    }
    work_included = {key for e in work.get("IncludedFiles", []) if (key := _included_key(e))}
    base_included = {key for e in base.get("IncludedFiles", []) if (key := _included_key(e))}
    entries: list[str] = []

    def add(entry: str) -> None:
        if entry not in entries:
            entries.append(entry)

    def add_folder_chain(folder_path: str) -> None:
        chain: list[str] = []
        current = PurePosixPath(folder_path)
        while current.as_posix() not in ("folders", "."):
            candidate = current.as_posix() if current.suffix == ".yy" else current.as_posix() + ".yy"
            if candidate in work_folders and candidate not in base_folders:
                chain.append(candidate)
            current = current.parent
        for candidate in reversed(chain):
            add(candidate)

    for raw in changed_paths:
        path = _norm(raw)
        parts = path.split("/")
        if parts[0] in ASSET_RESOURCE_TYPES and len(parts) >= 2:
            prefix = f"{parts[0]}/{parts[1]}/"
            candidates = sorted(p for p in work_resources | base_resources if p.startswith(prefix))
            for candidate in candidates:
                add(candidate)
                asset = load_json_loose(root / candidate) if (root / candidate).is_file() else None
                parent = asset.get("parent") if isinstance(asset, dict) and isinstance(asset.get("parent"), dict) else {}
                parent_path = _norm(str(parent.get("path", "")))
                if parent_path.startswith("folders/"):
                    add_folder_chain(parent_path)
        elif parts[0] == "datafiles":
            for key in sorted(work_included | base_included):
                if key == path or key.startswith(path + "/"):
                    add(INCLUDED_PREFIX + key)
        elif parts[0] == "folders":
            add(path)
    return entries
