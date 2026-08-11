from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from ..base_asset import BaseAsset
from ..utils import atomic_write_text
from .naming import get_config


class RoomAsset(BaseAsset):
    """GameMaker Room asset."""

    kind = "room"
    folder_prefix = "rooms"
    gm_tag = "GMRoom"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        width = kwargs.get("width", 1024)
        height = kwargs.get("height", 768)

        # GameMaker expects 8 view entries, each with a complete schema (even when disabled).
        # Using partial dicts (e.g. {"inherit": false, "visible": false}) causes IDE load failures.
        _view_template = {
            "hborder": 32,
            "hport": height,
            "hspeed": -1,
            "hview": height,
            "inherit": False,
            "objectId": None,
            "vborder": 32,
            "visible": False,
            "vspeed": -1,
            "wport": width,
            "wview": width,
            "xport": 0,
            "xview": 0,
            "yport": 0,
            "yview": 0,
        }

        return {
            "$GMRoom": "v1",
            "%Name": name,
            "creationCodeFile": "",
            "inheritCode": False,
            "inheritCreationOrder": False,
            "inheritLayers": False,
            "instanceCreationOrder": [],
            "isDnd": False,
            "layers": [
                {
                    "$GMRInstanceLayer": "",
                    "%Name": "Instances",
                    "depth": 0,
                    "effectEnabled": True,
                    "effectType": None,
                    "gridX": 32,
                    "gridY": 32,
                    "hierarchyFrozen": False,
                    "inheritLayerDepth": False,
                    "inheritLayerSettings": False,
                    "inheritSubLayers": False,
                    "inheritVisibility": False,
                    "instances": [],
                    "layers": [],
                    "name": "Instances",
                    "properties": [],
                    "resourceType": "GMRInstanceLayer",
                    "resourceVersion": "2.0",
                    "userdefinedDepth": False,
                    "visible": True,
                },
                {
                    "$GMRBackgroundLayer": "",
                    "%Name": "Background",
                    "animationFPS": 15.0,
                    "animationSpeedType": 0,
                    "colour": 4278190080,
                    "depth": 100,
                    "effectEnabled": True,
                    "effectType": None,
                    "gridX": 32,
                    "gridY": 32,
                    "hierarchyFrozen": False,
                    "hspeed": 0.0,
                    "htiled": False,
                    "inheritLayerDepth": False,
                    "inheritLayerSettings": False,
                    "inheritSubLayers": False,
                    "inheritVisibility": False,
                    "layers": [],
                    "name": "Background",
                    "properties": [],
                    "resourceType": "GMRBackgroundLayer",
                    "resourceVersion": "2.0",
                    "spriteId": None,
                    "stretch": False,
                    "userdefinedAnimFPS": False,
                    "userdefinedDepth": False,
                    "visible": True,
                    "vspeed": 0.0,
                    "vtiled": False,
                    "x": 0,
                    "y": 0,
                },
            ],
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "parentRoom": None,
            "physicsSettings": {
                "inheritPhysicsSettings": False,
                "PhysicsWorld": False,
                "PhysicsWorldGravityX": 0.0,
                "PhysicsWorldGravityY": 10.0,
                "PhysicsWorldPixToMetres": 0.1,
            },
            "resourceType": "GMRoom",
            "resourceVersion": "2.0",
            "roomSettings": {"Height": height, "inheritRoomSettings": False, "persistent": False, "Width": width},
            "sequenceId": None,
            "views": [_view_template.copy() for _ in range(8)],
            "viewSettings": {
                "clearDisplayBuffer": True,
                "clearViewBackground": False,
                "enableViews": False,
                "inheritViewSettings": False,
            },
            "volume": 1.0,
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Rooms don't typically have additional stub files
        pass

    def validate_name(self, name: str) -> bool:
        """Validate room name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("room")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class FolderAsset(BaseAsset):
    """GameMaker Folder asset."""

    kind = "folder"
    folder_prefix = "folders"  # Keep for compatibility, but not used for physical paths
    gm_tag = "GMFolder"

    def get_folder_path(self, project_root: Path, name: str) -> Path:
        # Folders are logical entities in GameMaker, not physical directories
        # Return the project root since folders don't have physical storage
        return project_root

    def get_yy_path(self, asset_folder: Path, name: str) -> Path:
        # Folders don't have physical .yy files in the normal sense
        # This method shouldn't be used for folders
        raise NotImplementedError("Folders don't have physical .yy files - they exist only in .yyp")

    def create_yy_data(self, name: str, parent_path: str = "", **kwargs) -> Dict[str, Any]:
        """Create the folder data structure for .yyp Folders list."""
        # Rules:
        # 1. If caller passes a path that already ends with '.yy' we use it verbatim.
        # 2. If caller passes a directory-like placeholder such as 'folders/' or
        #    'folders/SomeParent/' we treat it as a logical parent directory and append
        #    '<name>.yy'. We strip any trailing slash to avoid double slashes.
        # 3. If caller passes an empty string, create at project root as
        #    'folders/<name>.yy'.

        if not parent_path:
            folder_path = f"folders/{name}.yy"
        elif parent_path.rstrip().endswith(".yy"):
            # Check if parent_path already contains the target name (full path provided)
            if parent_path.rstrip().endswith(f"/{name}.yy"):
                # Full target path provided, use as-is
                folder_path = parent_path.rstrip()
            else:
                # For parent_path like "folders/UI.yy", create nested path "folders/UI/name.yy"
                parent_dir = parent_path.rstrip().rstrip(".yy")
                folder_path = f"{parent_dir}/{name}.yy"
        else:
            # Treat as logical directory path
            clean_parent = parent_path.rstrip("/")
            if not clean_parent:
                clean_parent = "folders"
            folder_path = f"{clean_parent}/{name}.yy"

        return {
            "$GMFolder": "",
            "%Name": name,
            "folderPath": folder_path,
            "name": name,
            "resourceType": "GMFolder",
            "resourceVersion": "2.0",
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Folders don't have physical files
        pass

    def create_files(self, project_root: Path, name: str, parent_path: str = "", **kwargs) -> str:
        """
        Create a folder entry in the .yyp file only.

        Unlike other assets, folders are purely logical constructs in GameMaker
        and exist only as entries in the .yyp file's Folders array.
        """
        try:
            from ..utils import load_json_loose, save_pretty_json, insert_into_folders
        except ImportError:
            from ..utils import load_json_loose, save_pretty_json, insert_into_folders

        # Determine the folder path for the .yyp entry
        if not parent_path:
            folder_path = f"folders/{name}.yy"
        elif parent_path.rstrip().endswith(".yy"):
            # Check if parent_path already contains the target name (full path provided)
            if parent_path.rstrip().endswith(f"/{name}.yy"):
                # Full target path provided, use as-is
                folder_path = parent_path.rstrip()
            else:
                # For parent_path like "folders/UI.yy", create nested path "folders/UI/name.yy"
                parent_dir = parent_path.rstrip().rstrip(".yy")
                folder_path = f"{parent_dir}/{name}.yy"
        else:
            # Treat as logical directory path
            clean_parent = parent_path.rstrip("/")
            if not clean_parent:
                clean_parent = "folders"
            folder_path = f"{clean_parent}/{name}.yy"

        # Load the .yyp file
        from pathlib import Path

        yyp_files = list(project_root.glob("*.yyp"))
        if not yyp_files:
            raise FileNotFoundError("No .yyp file found in project root")

        yyp_file = yyp_files[0]
        project_data = load_json_loose(yyp_file)
        if project_data is None:
            raise ValueError(f"Could not load {yyp_file}")

        # Add folder to the Folders section
        folders = project_data.get("Folders", project_data.get("folders", []))
        if not isinstance(folders, list):
            raise ValueError("Folders must be a list")
        from ..exceptions import AssetExistsError

        if any(
            isinstance(folder, dict)
            and (
                str(folder.get("name") or "").casefold() == name.casefold()
                or str(folder.get("folderPath") or "").replace("\\", "/").casefold() == folder_path.casefold()
            )
            for folder in folders
        ):
            raise AssetExistsError(
                f"Folder destination collision for '{name}'; provide a replacement name. "
                "Existing folders are never reused."
            )
        success = insert_into_folders(folders, name, folder_path)

        if success:
            project_data["Folders"] = folders
            project_data.pop("folders", None)
            save_pretty_json(yyp_file, project_data)
            print(f"[OK] Added folder '{name}' to {yyp_file.name} Folders list")
        else:
            print(f"ℹ Folder '{name}' already exists in {yyp_file.name} Folders list")

        # Return the logical path for consistency with other assets
        return folder_path

    def validate_name(self, name: str) -> bool:
        """Validate folder name against configured pattern."""
        if not name:
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("folder")
        if not rule:
            # Fallback to default folder validation
            allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_/ ")
            return all(c in allowed_chars for c in name)
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class NoteAsset(BaseAsset):
    """GameMaker Note asset."""

    kind = "note"
    folder_prefix = "notes"
    gm_tag = "GMNotes"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Note configuration parameters
        # NOTE: content is stored in the companion .txt file; keep kwargs handling here for consistency,
        # and ensure None does not propagate to file writes.
        _ = (
            kwargs.get("content")
            or f"# {name}\n\nThis is a note created by the CLI helper tools.\n\nAdd your documentation here."
        )

        return {
            "$GMNotes": "",
            "%Name": name,
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "resourceType": "GMNotes",
            "resourceVersion": "2.0",
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Create the note content file
        note_path = asset_folder / f"{name}.txt"
        if not note_path.exists():
            content = (
                kwargs.get("content")
                or f"# {name}\n\nThis is a note created by the CLI helper tools.\n\nAdd your documentation here."
            )
            atomic_write_text(note_path, content)
            print(f"Created {note_path.name}")

    def validate_name(self, name: str) -> bool:
        """Validate note name against configured pattern."""
        if not name:
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("note")
        if not rule:
            # Fallback to default note validation
            allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")
            return all(c in allowed_chars for c in name)
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))
