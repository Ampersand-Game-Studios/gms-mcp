from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from ..base_asset import BaseAsset
from ..utils import create_dummy_png, ensure_directory, generate_uuid
from .naming import get_config


class SpriteAsset(BaseAsset):
    """GameMaker Sprite asset."""

    kind = "sprite"
    folder_prefix = "sprites"
    gm_tag = "GMSprite"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Multi-frame support: get frame_count, default to 1 for backwards compat
        frame_count = kwargs.get("frame_count", 1)
        if frame_count < 1:
            frame_count = 1

        # Custom dimensions (used by sprite import)
        width = kwargs.get("width", 1)
        height = kwargs.get("height", 1)

        # Generate UUIDs - one layer shared across all frames
        layer_uuid = generate_uuid()

        # Generate frame UUIDs and keyframe UUIDs
        frame_uuids = [generate_uuid() for _ in range(frame_count)]
        keyframe_uuids = [generate_uuid() for _ in range(frame_count)]

        # Build frames array
        frames = [
            {
                "$GMSpriteFrame": "",
                "%Name": frame_uuid,
                "name": frame_uuid,
                "resourceType": "GMSpriteFrame",
                "resourceVersion": "2.0",
            }
            for frame_uuid in frame_uuids
        ]

        # Build keyframes array
        keyframes = [
            {
                "$Keyframe<SpriteFrameKeyframe>": "",
                "Channels": {
                    "0": {
                        "$SpriteFrameKeyframe": "",
                        "Id": {"name": frame_uuids[i], "path": f"sprites/{name.lower()}/{name}.yy"},
                        "resourceType": "SpriteFrameKeyframe",
                        "resourceVersion": "2.0",
                    }
                },
                "Disabled": False,
                "id": keyframe_uuids[i],
                "IsCreationKey": False,
                "Key": float(i),
                "Length": 1.0,
                "resourceType": "Keyframe<SpriteFrameKeyframe>",
                "resourceVersion": "2.0",
                "Stretch": False,
            }
            for i in range(frame_count)
        ]

        return {
            "$GMSprite": "",
            "%Name": name,
            "bboxMode": 0,
            "bbox_bottom": height - 1 if height > 1 else 0,
            "bbox_left": 0,
            "bbox_right": width - 1 if width > 1 else 0,
            "bbox_top": 0,
            "collisionKind": 1,
            "collisionTolerance": 0,
            "DynamicTexturePage": False,
            "edgeFiltering": False,
            "For3D": False,
            "frames": frames,
            "gridX": 0,
            "gridY": 0,
            "height": height,
            "HTile": False,
            "layers": [
                {
                    "$GMImageLayer": "",
                    "%Name": layer_uuid,
                    "blendMode": 0,
                    "displayName": "default",
                    "isLocked": False,
                    "name": layer_uuid,
                    "opacity": 100.0,
                    "resourceType": "GMImageLayer",
                    "resourceVersion": "2.0",
                    "visible": True,
                }
            ],
            "name": name,
            "nineSlice": None,
            "origin": 0,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "preMultiplyAlpha": False,
            "resourceType": "GMSprite",
            "resourceVersion": "2.0",
            "sequence": {
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
                "length": float(frame_count),
                "lockOrigin": False,
                "moments": {
                    "resourceType": "KeyframeStore<MomentsEventKeyframe>",
                    "resourceVersion": "2.0",
                    "Keyframes": [],
                },
                "name": name,
                "playback": 1,
                "playbackSpeed": 30.0,
                "playbackSpeedType": 0,
                "resourceType": "GMSequence",
                "resourceVersion": "2.0",
                "showBackdrop": True,
                "showBackdropImage": False,
                "timeUnits": 1,
                "tracks": [
                    {
                        "$GMSpriteFramesTrack": "",
                        "builtinName": 0,
                        "events": [],
                        "inheritsTrackColour": True,
                        "interpolation": 1,
                        "isCreationTrack": False,
                        "keyframes": {
                            "resourceType": "KeyframeStore<SpriteFrameKeyframe>",
                            "resourceVersion": "2.0",
                            "Keyframes": keyframes,
                        },
                        "modifiers": [],
                        "name": "frames",
                        "resourceType": "GMSpriteFramesTrack",
                        "resourceVersion": "2.0",
                        "spriteId": None,
                        "trackColour": 0,
                        "tracks": [],
                        "traits": 0,
                    }
                ],
                "visibleRange": None,
                "volume": 1.0,
                "xorigin": 0,
                "yorigin": 0,
            },
            "swatchColours": None,
            "swfPrecision": 2.525,
            "textureGroupId": {"name": "Default", "path": "texturegroups/Default"},
            "type": 0,
            "VTile": False,
            "width": width,
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Get UUIDs from the .yy data we just created
        yy_path = asset_folder / f"{name}.yy"
        if yy_path.exists():
            try:
                from ..utils import load_json_loose
            except ImportError:
                from ..utils import load_json_loose
            yy_data = load_json_loose(yy_path)
            if not yy_data:
                return

            # Extract layer UUID (shared across all frames)
            layer_uuid = yy_data["layers"][0]["name"]

            # Create PNG files for each frame
            for frame in yy_data["frames"]:
                frame_uuid = frame["name"]

                # Create main image
                main_image_path = asset_folder / f"{frame_uuid}.png"
                if not main_image_path.exists():
                    create_dummy_png(main_image_path)
                    print(f"Created {main_image_path.name} (dummy image)")

                # Create layer directory and image
                # Directory structure: layers/[frame_uuid]/[layer_uuid].png
                layer_dir = asset_folder / "layers" / frame_uuid
                ensure_directory(layer_dir)

                layer_image_path = layer_dir / f"{layer_uuid}.png"
                if not layer_image_path.exists():
                    create_dummy_png(layer_image_path)
                    print(f"Created layers/{frame_uuid}/{layer_uuid}.png (dummy image)")

            frame_count = len(yy_data["frames"])
            if frame_count > 1:
                print(f"[OK] Created {frame_count}-frame sprite with dummy images")
            print(f"[WARN]  Replace dummy PNG files with actual artwork before using in GameMaker!")

    def validate_name(self, name: str) -> bool:
        """Validate sprite name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("sprite")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class FontAsset(BaseAsset):
    """GameMaker Font asset."""

    kind = "font"
    folder_prefix = "fonts"
    gm_tag = "GMFont"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Font configuration parameters
        font_name = kwargs.get("font_name", "Arial")
        size = kwargs.get("size", 12)
        bold = kwargs.get("bold", False)
        italic = kwargs.get("italic", False)
        charset = kwargs.get("charset", 0)
        aa_level = kwargs.get("aa_level", 1)

        return {
            "$GMFont": "",
            "%Name": name,
            "AntiAlias": aa_level,
            "applyKerning": 0,
            "ascender": int(size * 1.5),  # Approximation
            "ascenderOffset": 0,
            "bold": bold,
            "canGenerateBitmap": True,
            "charset": charset,
            "ConfigValues": {"desktop": {"textureGroupId": '{ "name":"fonts", "path":"texturegroups/fonts" }'}},
            "first": 0,
            "fontName": font_name,
            "glyphOperations": 0,
            "glyphs": {
                "32": {
                    "character": 32,
                    "h": int(size * 2.5),
                    "offset": 0,
                    "shift": int(size * 0.4),
                    "w": int(size * 0.4),
                    "x": 2,
                    "y": 2,
                }
            },
            "hinting": 0,
            "includeTTF": False,
            "interpreter": 0,
            "italic": italic,
            "kerningPairs": [],
            "last": 0,
            "lineHeight": int(size * 2),
            "maintainGms1Font": False,
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "pointRounding": 0,
            "ranges": [{"lower": 32, "upper": 127}, {"lower": 9647, "upper": 9647}],
            "regenerateBitmap": False,
            "resourceType": "GMFont",
            "resourceVersion": "2.0",
            "sampleText": "abcdef ABCDEF\\n0123456789 .,<>\"'&!?\\nthe quick brown fox jumps over the lazy dog\\nTHE QUICK BROWN FOX JUMPS OVER THE LAZY DOG\\nDefault character: ▯ (9647)",
            "sdfSpread": 8,
            "size": float(size),
            "styleName": "Regular",
            "textureGroupId": {"name": "Default", "path": "texturegroups/Default"},
            "TTFName": "",
            "usesSDF": kwargs.get("uses_sdf", True),
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Create a dummy font PNG file
        png_path = asset_folder / f"{name}.png"
        if not png_path.exists():
            create_dummy_png(png_path, width=512, height=512)
            print(f"Created {png_path.name} (dummy font texture)")
            print(f"[WARN]  Font will need to be regenerated in GameMaker IDE!")

    def validate_name(self, name: str) -> bool:
        """Validate font name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("font")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class ShaderAsset(BaseAsset):
    """GameMaker Shader asset."""

    kind = "shader"
    folder_prefix = "shaders"
    gm_tag = "GMShader"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        shader_type = kwargs.get("shader_type", 1)  # 1 = GLSL ES, 2 = GLSL, 3 = HLSL 9, 4 = HLSL 11

        return {
            "$GMShader": "",
            "%Name": name,
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "resourceType": "GMShader",
            "resourceVersion": "2.0",
            "type": shader_type,
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Create vertex shader file
        vsh_path = asset_folder / f"{name}.vsh"
        if not vsh_path.exists():
            vsh_content = """//
// Simple passthrough vertex shader
//
attribute vec3 in_Position;                  // (x,y,z)
//attribute vec3 in_Normal;                  // (x,y,z)     unused in this shader.
attribute vec4 in_Colour;                    // (r,g,b,a)
attribute vec2 in_TextureCoord;              // (u,v)

varying vec2 v_vTexcoord;
varying vec4 v_vColour;

void main()
{
    vec4 object_space_pos = vec4( in_Position.x, in_Position.y, in_Position.z, 1.0);
    gl_Position = gm_Matrices[MATRIX_WORLD_VIEW_PROJECTION] * object_space_pos;
    
    v_vColour = in_Colour;
    v_vTexcoord = in_TextureCoord;
}
"""
            vsh_path.write_text(vsh_content, encoding="utf-8")
            print(f"Created {vsh_path.name} (vertex shader)")

        # Create fragment shader file
        fsh_path = asset_folder / f"{name}.fsh"
        if not fsh_path.exists():
            fsh_content = """//
// Simple passthrough fragment shader
//
varying vec2 v_vTexcoord;
varying vec4 v_vColour;

void main()
{
    gl_FragColor = v_vColour * texture2D( gm_BaseTexture, v_vTexcoord );
}
"""
            fsh_path.write_text(fsh_content, encoding="utf-8")
            print(f"Created {fsh_path.name} (fragment shader)")

    def validate_name(self, name: str) -> bool:
        """Validate shader name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("shader")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class AnimCurveAsset(BaseAsset):
    """GameMaker Animation Curve asset."""

    kind = "animcurve"
    folder_prefix = "animcurves"
    gm_tag = "GMAnimCurve"

    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Animation curve parameters
        curve_type = kwargs.get("curve_type", "linear")  # linear, smooth, bezier, ease_in, ease_out

        # Default curve points for different types
        if curve_type == "smooth":
            points = [
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.0, "y": 0.0},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.5, "y": 0.5},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0},
            ]
        elif curve_type == "ease_in":
            points = [
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.0, "y": 0.0},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.15, "y": 0.03},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.5, "y": 0.25},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0},
            ]
        elif curve_type == "ease_out":
            points = [
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.0, "y": 0.0},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.5, "y": 0.75},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.85, "y": 0.97},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0},
            ]
        else:  # linear
            points = [
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.0, "y": 0.0},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0},
            ]

        return {
            "$GMAnimCurve": "",
            "%Name": name,
            "channels": [
                {
                    "$GMAnimCurveChannel": "",
                    "%Name": kwargs.get("channel_name", "curve"),
                    "colour": 4282401023,
                    "name": kwargs.get("channel_name", "curve"),
                    "points": points,
                    "resourceType": "GMAnimCurveChannel",
                    "resourceVersion": "2.0",
                    "visible": True,
                }
            ],
            "function": kwargs.get("function", 1),  # 0=linear, 1=smooth
            "name": name,
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "resourceType": "GMAnimCurve",
            "resourceVersion": "2.0",
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Animation curves don't have additional stub files
        pass

    def validate_name(self, name: str) -> bool:
        """Validate animation curve name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("animcurve")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))
