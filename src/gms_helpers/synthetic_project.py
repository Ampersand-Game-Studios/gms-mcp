"""Deterministic, public-safe GameMaker projects for smoke verification."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .asset_types import RoomAsset


_SAFE_PROJECT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def create_synthetic_project(project_root: Path, *, project_name: str, ide_version: str) -> Path:
    """Create a minimal GameMaker project containing no studio or host data."""
    if not _SAFE_PROJECT_NAME.fullmatch(project_name):
        raise ValueError("Synthetic project names must contain only letters, numbers, and underscores.")
    if not ide_version.strip():
        raise ValueError("Synthetic projects require an explicit GameMaker IDE version.")

    project_root = Path(project_root).resolve()
    if project_root.exists():
        shutil.rmtree(project_root)
    project_root.mkdir(parents=True)
    for directory in (
        "animcurves",
        "fonts",
        "folders",
        "notes",
        "objects",
        "paths",
        "rooms",
        "scripts",
        "sequences",
        "shaders",
        "sounds",
        "sprites",
        "tilesets",
        "timelines",
    ):
        (project_root / directory).mkdir()

    room_name = "r_mcp_smoke"
    room_relative_path = f"rooms/{room_name}/{room_name}.yy"
    room_path = project_root / room_relative_path
    room_path.parent.mkdir(parents=True)
    room_path.write_text(
        json.dumps(
            RoomAsset().create_yy_data(
                room_name,
                "folders/Rooms.yy",
                width=640,
                height=360,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    yyp_path = project_root / f"{project_name}.yyp"
    yyp_path.write_text(
        json.dumps(
            {
                "$GMProject": "v1",
                "%Name": project_name,
                "AudioGroups": [
                    {
                        "$GMAudioGroup": "v1",
                        "%Name": "audiogroup_default",
                        "exportDir": "",
                        "name": "audiogroup_default",
                        "resourceType": "GMAudioGroup",
                        "resourceVersion": "2.0",
                        "targets": -1,
                    }
                ],
                "configs": {"children": [], "name": "Default"},
                "defaultScriptType": 0,
                "Folders": [
                    {
                        "$GMFolder": "",
                        "%Name": "Rooms",
                        "folderPath": "folders/Rooms.yy",
                        "name": "Rooms",
                        "resourceType": "GMFolder",
                        "resourceVersion": "2.0",
                    }
                ],
                "ForcedPrefabProjectReferences": [],
                "IncludedFiles": [],
                "isEcma": False,
                "LibraryEmitters": [],
                "MetaData": {"IDEVersion": ide_version},
                "name": project_name,
                "resources": [{"id": {"name": room_name, "path": room_relative_path}}],
                "resourceType": "GMProject",
                "resourceVersion": "2.0",
                "RoomOrderNodes": [{"roomId": {"name": room_name, "path": room_relative_path}}],
                "templateType": "game",
                "TextureGroups": [
                    {
                        "$GMTextureGroup": "",
                        "%Name": "Default",
                        "autocrop": True,
                        "border": 2,
                        "compressFormat": "bz2",
                        "customOptions": "",
                        "directory": "",
                        "groupParent": None,
                        "isScaled": True,
                        "loadType": "default",
                        "mipsToGenerate": 0,
                        "name": "Default",
                        "resourceType": "GMTextureGroup",
                        "resourceVersion": "2.0",
                        "targets": -1,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return yyp_path
