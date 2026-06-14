from __future__ import annotations

from .code import ObjectAsset, ScriptAsset
from .media import PathAsset, SequenceAsset, SoundAsset, TileSetAsset, TimelineAsset
from .project import FolderAsset, NoteAsset, RoomAsset
from .visual import AnimCurveAsset, FontAsset, ShaderAsset, SpriteAsset

ASSET_TYPES = {
    "script": ScriptAsset(),
    "object": ObjectAsset(),
    "sprite": SpriteAsset(),
    "room": RoomAsset(),
    "folder": FolderAsset(),
    "font": FontAsset(),
    "shader": ShaderAsset(),
    "animcurve": AnimCurveAsset(),
    "sound": SoundAsset(),
    "path": PathAsset(),
    "tileset": TileSetAsset(),
    "timeline": TimelineAsset(),
    "sequence": SequenceAsset(),
    "note": NoteAsset(),
}
