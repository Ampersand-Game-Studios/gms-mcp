from __future__ import annotations

import re
import wave
from pathlib import Path
from typing import Any, Dict

from ..base_asset import BaseAsset
from .naming import get_config


class SoundAsset(BaseAsset):
    """GameMaker Sound asset."""

    kind = "sound"
    folder_prefix = "sounds"
    gm_tag = "GMSound"

    _FORMAT_TO_EXTENSION = {
        0: "ogg",
        1: "mp3",
        2: "wav",
    }

    @classmethod
    def _normalize_format(cls, sound_format: Any) -> int:
        """Return a supported sound format index."""
        try:
            parsed = int(sound_format)
        except (TypeError, ValueError):
            return 2
        return parsed if parsed in cls._FORMAT_TO_EXTENSION else 2

    @classmethod
    def _requested_extension(cls, sound_format: Any) -> str:
        return cls._FORMAT_TO_EXTENSION[cls._normalize_format(sound_format)]

    @classmethod
    def _placeholder_extension(cls, sound_format: Any) -> str:
        # We generate a real silent WAV placeholder so fresh projects compile.
        _ = sound_format
        return "wav"

    @staticmethod
    def _write_silent_wav(path: Path, sample_rate: int = 44100, duration_seconds: float = 0.25) -> None:
        """Write a valid mono 16-bit PCM silent WAV file."""
        safe_rate = 44100
        try:
            parsed_rate = int(sample_rate)
            if parsed_rate > 0:
                safe_rate = parsed_rate
        except (TypeError, ValueError):
            pass

        frame_count = max(1, int(safe_rate * max(duration_seconds, 0.01)))

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit PCM
            wav_file.setframerate(safe_rate)
            wav_file.writeframes(b"\x00\x00" * frame_count)

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Sound configuration parameters
        volume = kwargs.get("volume", 1.0)
        pitch = kwargs.get("pitch", 1.0)
        sound_type = kwargs.get("sound_type", 0)  # 0=normal, 1=background, 2=3D
        bitrate = kwargs.get("bitrate", 128)
        sample_rate = kwargs.get("sample_rate", 44100)
        sound_format = kwargs.get("format", 0)  # 0=OGG, 1=MP3, 2=WAV
        sound_file_ext = self._placeholder_extension(sound_format)

        return {
            "$GMSound": "",
            "%Name": name,
            "audioGroupId": {"name": "audiogroup_default", "path": "audiogroups/audiogroup_default"},
            "bitDepth": 1,
            "bitRate": bitrate,
            "compression": 0,
            "conversionMode": 0,
            "duration": 1.0,
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "preload": False,
            "resourceType": "GMSound",
            "resourceVersion": "2.0",
            "sampleRate": sample_rate,
            "soundFile": f"{name}.{sound_file_ext}",
            "type": sound_type,
            "volume": volume,
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        requested_ext = self._requested_extension(kwargs.get("format", 0))
        placeholder_ext = self._placeholder_extension(kwargs.get("format", 0))
        sample_rate = kwargs.get("sample_rate", 44100)

        placeholder_path = asset_folder / f"{name}.{placeholder_ext}"
        if not placeholder_path.exists():
            self._write_silent_wav(placeholder_path, sample_rate=sample_rate)
            print(f"Created {placeholder_path.name} (silent placeholder audio)")
            if requested_ext != placeholder_ext:
                print(
                    f"[WARN]  Requested .{requested_ext} placeholder is unsupported; "
                    f"created .{placeholder_ext} instead for build compatibility."
                )
            print(f"[WARN]  Replace placeholder audio with real content before shipping.")

    def validate_name(self, name: str) -> bool:
        """Validate sound name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("sound")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class PathAsset(BaseAsset):
    """GameMaker Path asset."""

    kind = "path"
    folder_prefix = "paths"
    gm_tag = "GMPath"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Path configuration parameters
        closed = kwargs.get("closed", False)
        precision = kwargs.get("precision", 4)
        path_type = kwargs.get("path_type", "straight")  # straight, smooth

        # Create basic path points based on type
        if path_type == "smooth":
            points = [
                {"speed": 100.0, "x": 0.0, "y": 0.0},
                {"speed": 100.0, "x": 100.0, "y": 50.0},
                {"speed": 100.0, "x": 200.0, "y": 0.0},
                {"speed": 100.0, "x": 300.0, "y": -50.0},
            ]
        elif path_type == "circle":
            # Create a circular path
            import math

            points = []
            for i in range(8):
                angle = (i / 8.0) * 2 * math.pi
                x = 100 * math.cos(angle)
                y = 100 * math.sin(angle)
                points.append({"speed": 100.0, "x": float(x), "y": float(y)})
        else:  # straight
            points = [
                {"speed": 100.0, "x": 0.0, "y": 0.0},
                {"speed": 100.0, "x": 100.0, "y": 0.0},
                {"speed": 100.0, "x": 200.0, "y": 0.0},
            ]

        return {
            "$GMPath": "",
            "%Name": name,
            "closed": closed,
            "kind": 1 if path_type == "smooth" else 0,  # 0=straight lines, 1=smooth curve
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "points": points,
            "precision": precision,
            "resourceType": "GMPath",
            "resourceVersion": "2.0",
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Paths don't have additional stub files
        pass

    def validate_name(self, name: str) -> bool:
        """Validate path name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("path")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class TileSetAsset(BaseAsset):
    """GameMaker Tileset asset."""

    kind = "tileset"
    folder_prefix = "tilesets"
    gm_tag = "GMTileSet"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Tileset configuration parameters
        tile_width = kwargs.get("tile_width", 32)
        tile_height = kwargs.get("tile_height", 32)
        tile_xsep = kwargs.get("tile_xsep", 0)
        tile_ysep = kwargs.get("tile_ysep", 0)
        tile_xoff = kwargs.get("tile_xoff", 0)
        tile_yoff = kwargs.get("tile_yoff", 0)
        sprite_id = kwargs.get("sprite_id", None)

        sprite_ref = None
        if sprite_id:
            sprite_ref = {"name": sprite_id, "path": f"sprites/{sprite_id}/{sprite_id}.yy"}

        return {
            "$GMTileSet": "v1",
            "%Name": name,
            "autoTileSets": [],
            "macroPageTiles": {"SerialiseHeight": 0, "SerialiseWidth": 0, "TileSerialiseData": []},
            "name": name,
            "out_columns": int(256 / tile_width),  # Reasonable default
            "out_tilehborder": tile_xsep,
            "out_tilevborder": tile_ysep,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "resourceType": "GMTileSet",
            "resourceVersion": "2.0",
            "spriteId": sprite_ref,
            "spriteNoExport": True,
            "textureGroupId": {"name": "Default", "path": "texturegroups/Default"},
            "tileAnimationFrames": [],
            "tileAnimationSpeed": 15.0,
            "tileHeight": tile_height,
            "tilehsep": tile_xsep,
            "tilevsep": tile_ysep,
            "tileWidth": tile_width,
            "tilexoff": tile_xoff,
            "tileyoff": tile_yoff,
            "tile_count": 1,
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Tilesets don't have additional stub files (they reference sprites)
        pass

    def validate_name(self, name: str) -> bool:
        """Validate tileset name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("tileset")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class TimelineAsset(BaseAsset):
    """GameMaker Timeline asset."""

    kind = "timeline"
    folder_prefix = "timelines"
    gm_tag = "GMTimeline"

    @staticmethod
    def _normalize_moment(moment: Any, index: int) -> Dict[str, Any]:
        """Convert loose timeline moment input into a GameMaker-safe moment entry."""
        raw_moment = moment if isinstance(moment, dict) else {}
        raw_event = raw_moment.get("evnt")
        if not isinstance(raw_event, dict):
            raw_event = {}

        try:
            moment_value = int(raw_moment.get("moment", index))
        except (TypeError, ValueError):
            moment_value = index

        moment_name = raw_moment.get("%Name") or raw_moment.get("name") or f"moment_{moment_value}"
        event_name = raw_event.get("%Name") or raw_event.get("name") or f"ev_{moment_value}"

        try:
            event_num = int(raw_event.get("eventNum", 0))
        except (TypeError, ValueError):
            event_num = 0

        try:
            event_type = int(raw_event.get("eventType", 0))
        except (TypeError, ValueError):
            event_type = 0

        return {
            "$GMMoment": raw_moment.get("$GMMoment", ""),
            "%Name": str(moment_name),
            "name": str(moment_name),
            "moment": moment_value,
            "evnt": {
                "$GMEvent": raw_event.get("$GMEvent", ""),
                "%Name": str(event_name),
                "isDnD": bool(raw_event.get("isDnD", False)),
                "eventNum": event_num,
                "eventType": event_type,
                "collisionObjectId": raw_event.get("collisionObjectId"),
                "name": str(event_name),
                "resourceType": "GMEvent",
                "resourceVersion": "2.0",
            },
            "resourceType": "GMMoment",
            "resourceVersion": "2.0",
        }

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Build a compiler-safe default timeline shape.
        raw_moments = kwargs.get("moments")
        if not isinstance(raw_moments, list) or not raw_moments:
            raw_moments = [{"moment": 0}]
        moments = [self._normalize_moment(moment, index) for index, moment in enumerate(raw_moments)]

        return {
            "$GMTimeline": "",
            "%Name": name,
            "momentList": moments,
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "resourceType": "GMTimeline",
            "resourceVersion": "2.0",
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Create a moment_0.gml file for the first timeline moment
        moment_path = asset_folder / "moment_0.gml"
        if not moment_path.exists():
            moment_content = f"""/// Timeline moment 0 for {name}
// Add timeline actions here
// This code runs at moment 0 of the timeline
"""
            moment_path.write_text(moment_content, encoding="utf-8")
            print(f"Created moment_0.gml")

    def validate_name(self, name: str) -> bool:
        """Validate timeline name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("timeline")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class SequenceAsset(BaseAsset):
    """GameMaker Sequence asset."""

    kind = "sequence"
    folder_prefix = "sequences"
    gm_tag = "GMSequence"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Sequence configuration parameters
        length = kwargs.get("length", 60.0)  # 60 frames default
        playback_speed = kwargs.get("playback_speed", 30.0)  # 30 FPS

        return {
            "$GMSequence": "v1",
            "%Name": name,
            "autoRecord": True,
            "backdropHeight": 768,
            "backdropImageOpacity": 0.5,
            "backdropImagePath": "",
            "backdropWidth": 1366,
            "backdropXOffset": 0.0,
            "backdropYOffset": 0.0,
            "events": {
                "resourceType": "KeyframeStore<MessageEventKeyframe>",
                "resourceVersion": "2.0",
                "Keyframes": [],
            },
            "eventStubScript": None,
            "eventToFunction": {},
            "length": length,
            "lockOrigin": False,
            "moments": {
                "resourceType": "KeyframeStore<MomentsEventKeyframe>",
                "resourceVersion": "2.0",
                "Keyframes": [],
            },
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "playback": 1,
            "playbackSpeed": playback_speed,
            "playbackSpeedType": 0,
            "resourceType": "GMSequence",
            "resourceVersion": "2.0",
            "showBackdrop": True,
            "showBackdropImage": False,
            "timeUnits": 1,
            "tracks": [],
            "visibleRange": None,
            "volume": 1.0,
            "xorigin": 0,
            "yorigin": 0,
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Sequences don't have additional stub files
        pass

    def validate_name(self, name: str) -> bool:
        """Validate sequence name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("sequence")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))
