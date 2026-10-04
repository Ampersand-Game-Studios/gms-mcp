"""Read-only validation of modern GameMaker's project and embedded resource graph.

References are traversed recursively, including configuration overrides and nested
sequence tracks. Embedded identities (frames, properties and room items) are not
project resources, even though GameMaker uses the same name/path wire format.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .exceptions import AssetNotFoundError, ValidationError
from .utils import find_yyp, load_json_loose, strip_trailing_commas


ASSET_RESOURCE_TYPES = {
    "scripts": "GMScript",
    "objects": "GMObject",
    "sprites": "GMSprite",
    "rooms": "GMRoom",
    "fonts": "GMFont",
    "shaders": "GMShader",
    "animcurves": "GMAnimCurve",
    "sounds": "GMSound",
    "paths": "GMPath",
    "tilesets": "GMTileSet",
    "timelines": "GMTimeline",
    "sequences": "GMSequence",
    "notes": "GMNotes",
    "extensions": "GMExtension",
    "particles": "GMParticleSystem",
}
REFERENCE_TYPES = {
    "spriteId": "GMSprite",
    "spriteMaskId": "GMSprite",
    "parentObjectId": "GMObject",
    "collisionObjectId": "GMObject",
    "objectId": "GMObject",
    "parentRoom": "GMRoom",
    "roomId": "GMRoom",
    "sequenceId": "GMSequence",
    "tilesetId": "GMTileSet",
    "tileSetId": "GMTileSet",
    "pathId": "GMPath",
    "soundId": "GMSound",
    "fontId": "GMFont",
    "animCurveId": "GMAnimCurve",
    "animationCurveId": "GMAnimCurve",
    "eventStubScript": "GMScript",
    "particleSystemId": "GMParticleSystem",
    "textureGroupId": "GMTextureGroup",
    "audioGroupId": "GMAudioGroup",
    "groupParent": "GMTextureGroup",
    "propertyId": "GMObject",
    "instanceId": "GMRoom",
    "inheritedItemId": "GMRoom",
}
TRACK_REFERENCE_TYPES = {
    "GMSpriteTrack": "GMSprite",
    "GMSpriteFramesTrack": "GMSprite",
    "GMObjectTrack": "GMObject",
    "GMSequenceTrack": "GMSequence",
    "GMAudioTrack": "GMSound",
    "GMParticleTrack": "GMParticleSystem",
}
ROOM_LAYER_TYPES = {
    "GMRInstanceLayer",
    "GMRBackgroundLayer",
    "GMRAssetLayer",
    "GMRTileLayer",
    "GMRPathLayer",
    "GMREffectLayer",
    "GMRLayer",
    "GMRFolderLayer",
}
# Explicit packaged-file fields, not arbitrary strings or original import paths.
# Native extension .ext containers and optionsFile are metadata/generated outputs.
ASSET_FILE_FIELDS = {
    "GMSound": {"soundFile": frozenset({".wav", ".ogg", ".mp3"})},
    "GMFont": {"TTFName": frozenset({".ttf", ".otf"}), "texture": frozenset({".png"})},
    "GMExtension": {"helpfile": None},
}
_IGNORED = {".git", ".gms_mcp", ".gms-mcp", "output", "__pycache__", ".pytest_cache"}


@dataclass
class ProjectValidationResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    yyp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def safe_project_path(root: Path, value: Any) -> Path | None:
    """Reject ambiguous and escaping paths before any filesystem read."""
    if not isinstance(value, str) or not value or "\0" in value:
        return None
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if (
        PureWindowsPath(value).drive
        or ":" in normalized
        or normalized.startswith("/")
        or any(p in {"", ".", ".."} for p in parts)
    ):
        return None
    target = root.joinpath(*parts)
    try:
        if not target.resolve().is_relative_to(root.resolve()):
            return None
    except (OSError, ValueError):
        return None
    return target


def resolve_asset_reference(project_root: str | Path, name: str, expected_type: str) -> dict[str, str]:
    """Resolve the registered spelling/path rather than guessing a disk slug."""
    root = Path(project_root).resolve()
    from .path_safety import validate_resource_name

    name = validate_resource_name(name, "reference")
    yyp_path = find_yyp(root)
    if safe_project_path(root, yyp_path.name) is None:
        raise ValidationError("Unsafe project file path")
    project = load_json_loose(yyp_path)
    if not isinstance(project, dict) or not isinstance(project.get("resources", []), list):
        raise ValidationError("Malformed project resources")
    matches = [
        entry["id"]
        for entry in project.get("resources", [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), dict) and entry["id"].get("name") == name
    ]
    if not matches:
        raise AssetNotFoundError(f"Reference '{name}' is not a registered {expected_type}")
    if len(matches) != 1:
        raise ValidationError(f"Reference '{name}' must identify exactly one registered {expected_type}")
    reference = matches[0]
    path = safe_project_path(root, reference.get("path"))
    if path is None or not isinstance(reference.get("path"), str):
        raise ValidationError(f"Reference '{name}' has an unsafe or malformed path")
    data = load_json_loose(path) if path is not None and path.is_file() else None
    parts = reference["path"].replace("\\", "/").split("/")
    if (
        len(parts) != 3
        or ASSET_RESOURCE_TYPES.get(parts[0]) != expected_type
        or parts[-1] != f"{name}.yy"
        or not isinstance(data, dict)
        or data.get("resourceType") != expected_type
        or data.get("name") != name
        or data.get("%Name", name) != name
    ):
        raise ValidationError(f"Reference '{name}' is missing, unsafe, or not a {expected_type}")
    return {"name": name, "path": reference["path"].replace("\\", "/")}


def resolve_parent_reference(project_root: str | Path, parent_path: str) -> dict[str, str]:
    """Resolve the logical parent's registered identity, not its filename stem."""
    root = Path(project_root).resolve()
    path = parent_path.replace("\\", "/")
    if safe_project_path(root, path) is None:
        raise ValidationError(f"Unsafe parent folder path: {parent_path}")
    yyp = find_yyp(root)
    if safe_project_path(root, yyp.name) is None:
        raise ValidationError("Unsafe project file path")
    if path == yyp.name:
        return {"name": yyp.stem, "path": path}
    project = load_json_loose(yyp)
    if not isinstance(project, dict):
        raise ValidationError("Malformed project")
    folders = project.get("Folders", project.get("folders", []))
    if not isinstance(folders, list):
        raise ValidationError("Project Folders must be an array")
    matches = [
        folder
        for folder in folders
        if isinstance(folder, dict) and str(folder.get("folderPath", "")).replace("\\", "/") == path
    ]
    if len(matches) != 1 or not path.startswith("folders/") or not path.endswith(".yy"):
        raise ValidationError(f"Parent folder path '{parent_path}' must identify exactly one project folder")
    folder = matches[0]
    name = folder.get("name")
    if (
        not isinstance(name, str)
        or not name
        or folder.get("%Name", name) != name
        or folder.get("resourceType", "GMFolder") != "GMFolder"
    ):
        raise ValidationError(f"Malformed parent folder identity: {parent_path}")
    return {"name": name, "path": path}


class _ProjectGraph:
    def __init__(self, root: Path, project: dict[str, Any], result: ProjectValidationResult):
        self.root, self.project, self.result = root, project, result
        self.assets: dict[str, dict[str, Any]] = {}
        self.folders: dict[str, str] = {}
        self.groups: dict[str, tuple[str, str]] = {}

    def error(self, location: str, message: str) -> None:
        self.result.errors.append(f"{location}: {message}")

    def array(self, value: Any, location: str) -> list[Any]:
        if not isinstance(value, list):
            self.error(location, "expected an array")
            return []
        return value

    def index(self) -> None:
        folded: set[str] = set()
        for folder in self.array(self.project.get("Folders", self.project.get("folders", [])), "Folders"):
            if not isinstance(folder, dict):
                self.error("Folders", "malformed folder entry")
                continue
            path, name = folder.get("folderPath"), folder.get("name")
            if (
                not isinstance(path, str)
                or safe_project_path(self.root, path) is None
                or not path.replace("\\", "/").startswith("folders/")
                or not path.endswith(".yy")
                or not isinstance(name, str)
                or not name
            ):
                self.error("Folders", f"invalid folder identity {folder!r}")
                continue
            path = path.replace("\\", "/")
            if folder.get("resourceType", "GMFolder") != "GMFolder" or folder.get("%Name", name) != name:
                self.error(path, "mismatched folder identity or resourceType")
            if path.casefold() in folded:
                self.error(path, "duplicate folder path")
            folded.add(path.casefold())
            self.folders[path] = name
        for path in self.folders:
            parent = PurePosixPath(path).parent
            if parent.as_posix() != "folders" and parent.as_posix() + ".yy" not in self.folders:
                self.error(path, "missing enclosing folder")
        for field_name, prefix, resource_type in (
            ("TextureGroups", "texturegroups", "GMTextureGroup"),
            ("AudioGroups", "audiogroups", "GMAudioGroup"),
        ):
            for group in self.array(self.project.get(field_name, []), field_name):
                name = group.get("name") if isinstance(group, dict) else None
                if not isinstance(name, str) or not name:
                    self.error(field_name, "malformed group")
                    continue
                path = f"{prefix}/{name}"
                if (
                    safe_project_path(self.root, path) is None
                    or group.get("resourceType", resource_type) != resource_type
                    or group.get("%Name", name) != name
                ):
                    self.error(field_name, "invalid group identity or resourceType")
                    continue
                if path in self.groups:
                    self.error(path, "duplicate group")
                self.groups[path] = (name, resource_type)
        # Default groups are built into GameMaker, including minimal exported projects.
        self.groups.setdefault("texturegroups/Default", ("Default", "GMTextureGroup"))
        self.groups.setdefault("audiogroups/audiogroup_default", ("audiogroup_default", "GMAudioGroup"))
        names: set[str] = set()
        folded.clear()
        for entry in self.array(self.project.get("resources", []), "resources"):
            ref = entry.get("id") if isinstance(entry, dict) else None
            if not isinstance(ref, dict):
                self.error("resources", "malformed resource entry")
                continue
            path, name = ref.get("path"), ref.get("name")
            target = safe_project_path(self.root, path)
            if (
                target is None
                or not isinstance(path, str)
                or not isinstance(name, str)
                or not name
                or not path.endswith(".yy")
            ):
                self.error("resources", f"unsafe or malformed resource {ref!r}")
                continue
            path = path.replace("\\", "/")
            if path.casefold() in folded or name.casefold() in names:
                self.error(path, "duplicate resource name or path")
            folded.add(path.casefold())
            names.add(name.casefold())
            data = load_json_loose(target) if target.is_file() else None
            if not isinstance(data, dict):
                self.error(path, "missing file or invalid resource JSON")
                continue
            expected = ASSET_RESOURCE_TYPES.get(path.split("/")[0])
            if expected is None or len(path.split("/")) != 3 or PurePosixPath(path).name != f"{name}.yy":
                self.error(path, "unsupported resource location or filename")
            if expected is None or data.get("resourceType") != expected:
                self.error(path, f"expected resourceType {expected}")
            if data.get("name") != name or data.get("%Name", name) != name:
                self.error(path, "registered name does not match asset identity")
            self.assets[path] = data

    def reference(self, value: Any, key: str, location: str, owner: str, expected: str | None = None) -> None:
        expected = expected or REFERENCE_TYPES.get(key)
        if value is None:
            return
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("name"), str)
            or not value.get("name")
            or safe_project_path(self.root, value.get("path")) is None
        ):
            self.error(location, "malformed or unsafe reference")
            return
        path, name = value["path"].replace("\\", "/"), value["name"]
        if key == "parent":
            wanted = Path(self.result.yyp or "").stem if path == self.result.yyp else self.folders.get(path)
            if wanted is None or wanted != name:
                self.error(location, f"missing or mismatched parent folder '{path}'")
            return
        if path in self.groups:
            target_name, target_type = self.groups[path]
        else:
            target = self.assets.get(path)
            if target is None:
                self.error(location, f"missing registered target '{path}'")
                return
            target_name, target_type = target.get("name"), target.get("resourceType")
            if expected and target_type != expected:
                self.error(location, f"wrong target type {target_type}; expected {expected}")
                return
            # Embedded references name an item inside the resource identified by path.
            if key in {"frameId", "inheritedItemId", "propertyId", "instanceId"}:
                embedded = self.embedded_names(target, key)
                if name in embedded:
                    if key == "inheritedItemId" and path not in self.ancestors(owner, "parentRoom"):
                        self.error(location, "inherited item does not belong to an ancestor room")
                    if key == "frameId" and path != owner:
                        self.error(location, "sprite frame does not belong to its owning sprite")
                    return
                self.error(location, f"missing embedded identity '{name}' in '{path}'")
                return
        if target_name != name:
            self.error(location, f"reference name '{name}' does not match target '{target_name}'")
        if expected and target_type != expected:
            self.error(location, f"wrong target type {target_type}; expected {expected}")

    @staticmethod
    def embedded_names(data: dict[str, Any], key: str) -> set[str]:
        wanted = (
            {"GMSpriteFrame"}
            if key == "frameId"
            else {"GMRInstance"}
            if key == "instanceId"
            else {"GMRInstance", "GMRSpriteGraphic", "GMRSequence", "GMRParticleSystem"}
        )
        if key == "propertyId":
            wanted = {"GMObjectProperty"}
        if key == "inheritedItemId":
            wanted.update(ROOM_LAYER_TYPES)
        names: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("resourceType") in wanted and isinstance(value.get("name"), str):
                    names.add(value["name"])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        if key == "frameId":
            walk(data.get("frames", []))
        elif key == "propertyId":
            walk(data.get("properties", []))
        else:
            walk(data.get("layers", []))
        return names

    def ancestors(self, owner: str, key: str) -> set[str]:
        paths: set[str] = set()
        current = owner
        while current in self.assets:
            ref = self.assets[current].get(key)
            target = ref.get("path") if isinstance(ref, dict) else None
            if not isinstance(target, str):
                break
            target = target.replace("\\", "/")
            if target in paths:
                break
            paths.add(target)
            current = target
        return paths

    def walk(self, value: Any, location: str, owner: str, key: str = "", track_type: str = "") -> None:
        if key == "groupParent" and isinstance(value, str):
            if not value:
                return
            value = {"name": value, "path": f"texturegroups/{value}"}
        if isinstance(value, str) and key in REFERENCE_TYPES:
            try:
                value = json.loads(strip_trailing_commas(value))
            except (ValueError, TypeError):
                self.error(location, "invalid serialized configuration reference")
                return
        if key == "Id":
            # Id in asset channels is a reference; lowercase keyframe id and other
            # primitive embedded identifiers are not project registrations.
            if track_type in TRACK_REFERENCE_TYPES or isinstance(value, dict):
                self.reference(
                    value,
                    "frameId" if track_type == "GMSpriteFramesTrack" else key,
                    location,
                    owner,
                    TRACK_REFERENCE_TYPES.get(track_type),
                )
            return
        if key in REFERENCE_TYPES or key in {"parent", "inheritedItemId", "propertyId", "instanceId"}:
            self.reference(value, key, location, owner)
            return
        if isinstance(value, dict):
            if isinstance(value.get("propertyId"), dict) and isinstance(value.get("objectId"), dict):
                if value["propertyId"].get("path") != value["objectId"].get("path"):
                    self.error(location, "property reference and declaring object disagree")
            if "path" in value and "name" in value and not "resourceType" in value:
                self.reference(value, key, location, owner, TRACK_REFERENCE_TYPES.get(track_type))
                return
            track_type = (
                value.get("resourceType", track_type)
                if str(value.get("resourceType", "")).endswith("Track")
                else track_type
            )
            for child_key, child in value.items():
                if child_key == "instanceCreationOrder":
                    continue  # Room-local references are checked with inheritance below.
                self.walk(child, f"{location}.{child_key}", owner, child_key, track_type)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.walk(child, f"{location}[{index}]", owner, key, track_type)
        elif isinstance(value, str) and key in REFERENCE_TYPES:
            self.error(location, "reference must be an object")

    def events(self, data: dict[str, Any], path: str, *, check_files: bool = True) -> None:
        from .event_model import event_filename_from_entry, parse_event_filename

        expected: set[str] = set()
        for event in self.array(data.get("eventList", []), f"{path}.eventList"):
            if not isinstance(event, dict):
                self.error(path, "malformed event")
                continue
            try:
                if event.get("resourceType", "GMEvent") != "GMEvent":
                    raise ValidationError("invalid event resourceType")
                if type(event.get("eventType")) is not int or type(event.get("eventNum")) is not int:
                    raise ValidationError("eventType and eventNum must be integers")
                filename = event_filename_from_entry(event)
                if event["eventNum"] < 0 or (event["eventType"] in {-1, 0, 1, 4, 12} and event["eventNum"] != 0):
                    raise ValidationError("invalid event subtype")
                if event["eventType"] != 4 and event.get("collisionObjectId") is not None:
                    raise ValidationError("non-collision event has a collision target")
            except (ValueError, TypeError, ValidationError) as exc:
                self.error(path, f"invalid event: {exc}")
                continue
            if filename in expected:
                self.error(path, f"duplicate event identity '{filename}'")
            expected.add(filename)
            identity = filename.removesuffix(".gml")
            # IDE versions also serialize unnamed events. Do not rewrite/reject those.
            if any(event.get(k) not in (None, "", identity) for k in ("name", "%Name")):
                self.error(path, f"event identity does not match '{filename}'")
            if not check_files:
                continue
            event_file = safe_project_path(self.root, str(PurePosixPath(path).parent / filename))
            if event_file is None or not event_file.is_file():
                if event.get("name") or event.get("%Name") or event.get("eventType") == 4:
                    self.error(path, f"event file is missing: {filename}")
                else:
                    self.result.warnings.append(f"{path}: metadata-only empty event: {filename}")
        for gml in (self.root / path).parent.glob("*.gml") if check_files else ():
            try:
                parse_event_filename(gml.name)
            except ValidationError:
                continue
            if gml.name not in expected:
                self.error(path, f"orphaned event file: {gml.name}")

    def room_order(self) -> None:
        seen: set[str] = set()
        for index, node in enumerate(self.array(self.project.get("RoomOrderNodes", []), "RoomOrderNodes")):
            location = f"RoomOrderNodes[{index}]"
            if not isinstance(node, dict) or not isinstance(node.get("roomId"), dict):
                self.error(location, "expected a room-reference node")
                continue
            reference = node["roomId"]
            self.walk(node, location, self.result.yyp or "")
            path = reference.get("path")
            if isinstance(path, str):
                normalized = path.replace("\\", "/").casefold()
                if normalized in seen:
                    self.error(location, "duplicate room-order entry")
                seen.add(normalized)

    def file_reference(
        self,
        value: Any,
        location: str,
        owner: str,
        *,
        extensions: frozenset[str] | None = None,
        project_relative: bool = False,
        check_files: bool = True,
        optional: bool = True,
    ) -> str | None:
        if optional and value in (None, ""):
            return None
        if not isinstance(value, str) or not value:
            self.error(location, "expected a file-reference string")
            return None
        normalized = value.replace("\\", "/")
        if project_relative:
            if normalized.startswith("${project_dir}/"):
                normalized = normalized.removeprefix("${project_dir}/")
            elif "/" not in normalized:
                normalized = str(PurePosixPath(owner).parent / normalized)
        else:
            if "/" in normalized:
                self.error(location, "expected an asset-relative file basename")
                return None
            normalized = str(PurePosixPath(owner).parent / normalized)
        target = safe_project_path(self.root, normalized)
        if target is None or "${" in normalized:
            self.error(location, "unsafe file reference")
            return None
        if extensions is not None and target.suffix.lower() not in extensions:
            self.error(location, "wrong referenced file type")
        if check_files and not target.is_file():
            self.error(location, "referenced file is missing or not a regular file")
        return normalized

    def file_references(self, data: dict[str, Any], path: str, *, check_files: bool = True) -> None:
        resource_type = str(data.get("resourceType"))
        fields = ASSET_FILE_FIELDS.get(resource_type, {})

        def fields_in(value: dict[str, Any], location: str) -> None:
            for key, extensions in fields.items():
                if key in value:
                    self.file_reference(
                        value[key], f"{location}.{key}", path, extensions=extensions, check_files=check_files
                    )
            if resource_type == "GMExtension" and "optionsFile" in value:
                self.file_reference(
                    value["optionsFile"],
                    f"{location}.optionsFile",
                    path,
                    extensions=frozenset({".json"}),
                    check_files=False,
                )
            if resource_type == "GMRoom" and "creationCodeFile" in value:
                parent = value.get("parentRoom", data.get("parentRoom"))
                parent_path = parent.get("path") if isinstance(parent, dict) else None
                parent_asset = (
                    self.assets.get(parent_path.replace("\\", "/"), {}) if isinstance(parent_path, str) else {}
                )
                inherited = (
                    value.get("inheritCode", data.get("inheritCode")) is True
                    and parent_asset.get("resourceType") == "GMRoom"
                )
                self.file_reference(
                    value["creationCodeFile"],
                    f"{location}.creationCodeFile",
                    path,
                    extensions=frozenset({".gml"}),
                    project_relative=True,
                    check_files=check_files and not inherited,
                )

        fields_in(data, path)
        configs = data.get("ConfigValues", {})
        if isinstance(configs, dict):
            for name, config in configs.items():
                if isinstance(config, dict):
                    fields_in(config, f"{path}.ConfigValues.{name}")
        if resource_type == "GMRoom":

            def instances(value: Any, location: str) -> None:
                if isinstance(value, dict):
                    if value.get("resourceType") == "GMRInstance":
                        fields_in({"inheritCode": False, **value}, location)
                        configs = value.get("ConfigValues", {})
                        if isinstance(configs, dict):
                            for name, config in configs.items():
                                if isinstance(config, dict):
                                    fields_in(
                                        {"inheritCode": value.get("inheritCode", False), **config},
                                        f"{location}.ConfigValues.{name}",
                                    )
                    for key, child in value.items():
                        instances(child, f"{location}.{key}")
                elif isinstance(value, list):
                    for index, child in enumerate(value):
                        instances(child, f"{location}[{index}]")

            instances(data.get("layers", []), f"{path}.layers")
        if resource_type == "GMExtension":
            for index, item in enumerate(self.array(data.get("files", []), f"{path}.files")):
                location = f"{path}.files[{index}]"
                if not isinstance(item, dict) or item.get("resourceType", "GMExtensionFile") != "GMExtensionFile":
                    self.error(location, "malformed extension file entry")
                    continue
                filename = item.get("filename")
                virtual = isinstance(filename, str) and filename.lower().endswith(".ext") and item.get("kind") == 4
                self.file_reference(
                    filename, location + ".filename", path, check_files=check_files and not virtual, optional=False
                )
                configs = item.get("ConfigValues", {})
                if isinstance(configs, dict):
                    for name, config in configs.items():
                        if isinstance(config, dict) and "filename" in config:
                            configured_filename = config["filename"]
                            configured_virtual = (
                                isinstance(configured_filename, str)
                                and configured_filename.lower().endswith(".ext")
                                and config.get("kind", item.get("kind")) == 4
                            )
                            self.file_reference(
                                configured_filename,
                                f"{location}.ConfigValues.{name}.filename",
                                path,
                                check_files=check_files and not configured_virtual,
                                optional=False,
                            )
                if item.get("name", filename) != filename or item.get("%Name", filename) != filename:
                    self.error(location, "mismatched extension file identity")
                for proxy_index, proxy in enumerate(self.array(item.get("ProxyFiles", []), location + ".ProxyFiles")):
                    proxy_location = f"{location}.ProxyFiles[{proxy_index}]"
                    if not isinstance(proxy, dict) or proxy.get("resourceType", "GMProxyFile") != "GMProxyFile":
                        self.error(proxy_location, "malformed extension proxy file")
                        continue
                    self.file_reference(
                        proxy.get("name"), proxy_location + ".name", path, check_files=check_files, optional=False
                    )
                    configs = proxy.get("ConfigValues", {})
                    if isinstance(configs, dict):
                        for name, config in configs.items():
                            if isinstance(config, dict) and "name" in config:
                                self.file_reference(
                                    config["name"],
                                    f"{proxy_location}.ConfigValues.{name}.name",
                                    path,
                                    check_files=check_files,
                                    optional=False,
                                )
                    if proxy.get("%Name", proxy.get("name")) != proxy.get("name"):
                        self.error(proxy_location, "mismatched extension proxy identity")

    def included_files(self) -> None:
        seen: set[str] = set()
        for index, item in enumerate(self.array(self.project.get("IncludedFiles", []), "IncludedFiles")):
            location = f"IncludedFiles[{index}]"
            if not isinstance(item, dict) or item.get("resourceType", "GMIncludedFile") != "GMIncludedFile":
                self.error(location, "malformed included-file entry")
                continue
            name, directory = item.get("name"), item.get("filePath")
            if (
                not isinstance(name, str)
                or not name
                or "/" in name
                or "\\" in name
                or not isinstance(directory, str)
                or not directory.replace("\\", "/").startswith("datafiles")
                or item.get("%Name", name) != name
            ):
                self.error(location, "invalid included-file identity or directory")
                continue
            relative = directory.replace("\\", "/") + "/" + name
            target = safe_project_path(self.root, relative)
            if target is None or relative.split("/")[0] != "datafiles":
                self.error(location, "unsafe included-file path")
                continue
            if relative.casefold() in seen:
                self.error(location, "duplicate included-file path")
            seen.add(relative.casefold())
            if not target.is_file():
                self.error(location, "included file is missing or not a regular file")

    def room(self, data: dict[str, Any], path: str) -> None:
        layers_seen: set[str] = set()
        instances: set[str] = set()
        items_seen: set[str] = set()

        def layers(value: Any, location: str) -> None:
            for layer in self.array(value, location):
                if not isinstance(layer, dict) or not isinstance(layer.get("name"), str) or not layer["name"]:
                    self.error(location, "malformed layer")
                    continue
                name = layer["name"]
                if name in layers_seen:
                    self.error(location, f"duplicate layer identity '{name}'")
                layers_seen.add(name)
                if layer.get("%Name", name) != name:
                    self.error(location, "mismatched layer identity")
                if layer.get("resourceType") not in ROOM_LAYER_TYPES:
                    self.error(location, "invalid layer resourceType")
                for item in self.array(layer.get("instances", []), location + ".instances"):
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("name"), str)
                        or not item["name"]
                        or item.get("resourceType") != "GMRInstance"
                    ):
                        self.error(location, "malformed instance")
                        continue
                    if layer.get("resourceType") != "GMRInstanceLayer":
                        self.error(location, "instance stored on a non-instance layer")
                    name = item["name"]
                    if name in items_seen or item.get("%Name", name) != name:
                        self.error(location, f"duplicate or mismatched instance identity '{name}'")
                    instances.add(name)
                    items_seen.add(name)
                    if item.get("objectId") is None and item.get("inheritedItemId") is None:
                        self.error(location, f"instance '{name}' has no object reference")
                for collection, item_type, reference_key in (
                    ("sprites", "GMRSpriteGraphic", "spriteId"),
                    ("sequences", "GMRSequence", "sequenceId"),
                    ("particleSystems", "GMRParticleSystem", "particleSystemId"),
                ):
                    for item in self.array(layer.get(collection, []), location + "." + collection):
                        if (
                            not isinstance(item, dict)
                            or not isinstance(item.get("name"), str)
                            or not item["name"]
                            or item.get("resourceType") != item_type
                        ):
                            self.error(location, f"malformed {collection} item")
                            continue
                        if layer.get("resourceType") != "GMRAssetLayer":
                            self.error(location, f"{collection} item stored on a non-asset layer")
                        if item.get(reference_key) is None and item.get("inheritedItemId") is None:
                            self.error(location, f"{collection} item has no resource reference")
                        if item["name"] in items_seen or item.get("%Name", item["name"]) != item["name"]:
                            self.error(location, f"duplicate or mismatched {collection} identity")
                        items_seen.add(item["name"])
                layers(layer.get("layers", []), location + ".layers")

        layers(data.get("layers", []), path + ".layers")
        inherited: set[str] = set()
        ancestor = data.get("parentRoom")
        visited = {path}
        while isinstance(ancestor, dict) and ancestor.get("path") in self.assets:
            ancestor_path = ancestor["path"]
            if ancestor_path in visited:
                break  # Graph-cycle diagnostic is emitted separately.
            visited.add(ancestor_path)
            parent = self.assets[ancestor_path]
            inherited.update(self.embedded_names(parent, "instanceId"))
            ancestor = parent.get("parentRoom")
        ordered: set[str] = set()
        for entry in self.array(data.get("instanceCreationOrder", []), path + ".instanceCreationOrder"):
            name = entry if isinstance(entry, str) else entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str) or name not in instances | inherited:
                self.error(path, f"creation order references missing instance '{name}'")
                continue
            if name in ordered:
                self.error(path, f"duplicate creation-order instance '{name}'")
            ordered.add(name)
            if isinstance(entry, dict):
                ref_path = entry.get("path")
                if (
                    not isinstance(ref_path, str)
                    or safe_project_path(self.root, ref_path) is None
                    or ref_path.replace("\\", "/") not in visited
                    or name not in self.embedded_names(self.assets.get(ref_path.replace("\\", "/"), {}), "instanceId")
                ):
                    self.error(path, f"creation-order instance '{name}' has wrong room path")
        if instances - ordered:
            self.error(path, f"instances missing from creation order: {sorted(instances - ordered)}")

    def timeline(self, data: dict[str, Any], path: str, *, check_files: bool = True) -> None:
        from .event_model import event_filename_from_entry

        seen: set[int] = set()
        for item in self.array(data.get("momentList", []), f"{path}.momentList"):
            if not isinstance(item, dict) or type(item.get("moment")) is not int or item["moment"] < 0:
                self.error(path, "malformed timeline moment")
                continue
            moment = item["moment"]
            if moment in seen or item.get("resourceType", "GMMoment") != "GMMoment":
                self.error(path, "duplicate moment or invalid timeline moment type")
            seen.add(moment)
            event = item.get("evnt")
            try:
                if (
                    not isinstance(event, dict)
                    or event.get("resourceType", "GMEvent") != "GMEvent"
                    or type(event.get("eventType")) is not int
                    or type(event.get("eventNum")) is not int
                ):
                    raise ValidationError("malformed timeline event")
                event_filename_from_entry(event)
            except (TypeError, ValueError, ValidationError) as exc:
                self.error(path, f"invalid timeline event: {exc}")
            if check_files and not (self.root / path).parent.joinpath(f"moment_{moment}.gml").is_file():
                self.error(path, f"timeline code is missing: moment_{moment}.gml")

    def embedded_identities(self, data: dict[str, Any], path: str) -> None:
        """Validate local identities without mistaking them for YYP registrations."""
        collections = {
            "GMSprite": (("frames", "GMSpriteFrame"), ("layers", "GMImageLayer")),
            "GMObject": (("properties", "GMObjectProperty"),),
        }
        for key, resource_type in collections.get(str(data.get("resourceType")), ()):
            seen: set[str] = set()
            for item in self.array(data.get(key, []), f"{path}.{key}"):
                if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
                    self.error(path, f"malformed embedded {key} identity")
                    continue
                name = item["name"]
                if name in seen or item.get("%Name", name) != name or item.get("resourceType") != resource_type:
                    self.error(path, f"duplicate or mismatched embedded {key} identity/type '{name}'")
                seen.add(name)

    def cycles(self, key: str) -> None:
        completed: set[str] = set()
        for start in self.assets:
            current = start
            seen: set[str] = set()
            while current in self.assets and current not in completed:
                if current in seen:
                    self.error(start, f"cyclic {key} inheritance")
                    break
                seen.add(current)
                ref = self.assets[current].get(key)
                target = ref.get("path") if isinstance(ref, dict) else None
                current = target.replace("\\", "/") if isinstance(target, str) else ""
            completed.update(seen)

    def containers(self, value: Any, location: str) -> None:
        """Check collection shape without prescribing every version-specific field."""
        array_keys = {
            "frames",
            "layers",
            "tracks",
            "Keyframes",
            "eventList",
            "momentList",
            "properties",
            "overriddenProperties",
            "views",
            "channels",
            "points",
            "assets",
            "paths",
            "sprites",
            "sequences",
            "particleSystems",
        }
        if isinstance(value, dict):
            for key, child in value.items():
                # Keyframe Channels is a keyed dictionary, animcurve channels an array.
                if key in array_keys and not isinstance(child, list):
                    self.error(f"{location}.{key}", "expected an array")
                if key == "Channels" and not isinstance(child, dict):
                    self.error(f"{location}.{key}", "expected keyed channels object")
                if key == "Keyframes" and isinstance(child, list):
                    ids: set[str] = set()
                    for item in child:
                        identity = item.get("id") if isinstance(item, dict) else None
                        if not isinstance(identity, str) or not identity or identity in ids:
                            self.error(f"{location}.{key}", "missing or duplicate keyframe identity")
                        else:
                            ids.add(identity)
                self.containers(child, f"{location}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.containers(child, f"{location}[{index}]")


def validate_project_after_mutation(project_root: str | Path) -> ProjectValidationResult:
    """Validate all registered assets and embedded references without changing files."""
    root = Path(project_root).resolve()
    result = ProjectValidationResult(True)
    yyps = sorted(root.glob("*.yyp"))
    if not yyps:
        return ProjectValidationResult(False, [f"No .yyp file found in {root}"])
    if len(yyps) > 1:
        result.warnings.append(f"Multiple .yyp files found; validating {yyps[0].name}")
    result.yyp = yyps[0].name
    if safe_project_path(root, result.yyp) is None:
        return ProjectValidationResult(False, ["Unsafe project file path"])
    project = load_json_loose(yyps[0])
    if not isinstance(project, dict):
        return ProjectValidationResult(False, [f"Invalid project JSON: {result.yyp}"], yyp=result.yyp)
    graph = _ProjectGraph(root, project, result)
    graph.index()
    for path, asset in graph.assets.items():
        if not isinstance(asset.get("parent"), dict):
            graph.error(path, "missing parent reference")
        graph.walk(asset, path, path)
        graph.containers(asset, path)
        graph.embedded_identities(asset, path)
        graph.file_references(asset, path)
        if asset.get("resourceType") == "GMObject":
            graph.events(asset, path)
        if asset.get("resourceType") == "GMRoom":
            graph.room(asset, path)
        if asset.get("resourceType") == "GMTimeline":
            graph.timeline(asset, path)
    graph.room_order()
    graph.included_files()
    graph.walk(project.get("TextureGroups", []), "TextureGroups", result.yyp)
    graph.cycles("parentObjectId")
    graph.cycles("parentRoom")
    for path in sorted(root.rglob("*.yy")):
        relative = path.relative_to(root)
        if any(part in _IGNORED for part in relative.parts) or path.name.endswith(".inherited.yy"):
            continue
        if relative.parts[0] == "options" and path.name.endswith((".desktop.yy", ".android.yy")):
            continue
        if safe_project_path(root, relative.as_posix()) is None:
            graph.error(relative.as_posix(), "unsafe JSON path")
        elif not isinstance(load_json_loose(path), dict):
            graph.error(relative.as_posix(), "Invalid JSON")
    result.success = not result.errors
    return result


def validate_asset_metadata_references(project_root: str | Path, relative_path: str, data: dict[str, Any]) -> None:
    """Preflight generated metadata, including self-owned frames, without writes."""
    root = Path(project_root).resolve()
    yyp = find_yyp(root)
    if safe_project_path(root, yyp.name) is None:
        raise ValidationError("Unsafe project file path")
    project = load_json_loose(yyp)
    if not isinstance(project, dict):
        raise ValidationError("Malformed project")
    result = ProjectValidationResult(True, yyp=yyp.name)
    graph = _ProjectGraph(root, project, result)
    graph.index()
    graph.assets[relative_path] = data
    # An omitted logical parent is assigned after metadata preflight. All other
    # references, including self-owned sprite frames, must already be valid.
    graph.walk({key: value for key, value in data.items() if key != "parent"}, relative_path, relative_path)
    graph.containers(data, relative_path)
    graph.embedded_identities(data, relative_path)
    graph.file_references(data, relative_path, check_files=False)
    if data.get("resourceType") == "GMRoom":
        graph.room(data, relative_path)
    if data.get("resourceType") == "GMObject":
        graph.events(data, relative_path, check_files=False)
    if data.get("resourceType") == "GMTimeline":
        graph.timeline(data, relative_path, check_files=False)
    if result.errors:
        raise ValidationError("Invalid asset metadata: " + "; ".join(result.errors))
