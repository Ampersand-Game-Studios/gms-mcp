from __future__ import annotations

from typing import Literal


OutputMode = Literal["full", "tail", "none"]
RunnerPlatform = Literal["Windows", "macOS", "Linux", "HTML5", "Android", "iOS", "GX.games"]
DeletableAssetType = Literal[
    "script",
    "object",
    "sprite",
    "room",
    "folder",
    "font",
    "shader",
    "animcurve",
    "sound",
    "path",
    "tileset",
    "timeline",
    "sequence",
    "note",
]
