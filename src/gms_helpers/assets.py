"""
Concrete implementations of GameMaker asset types
"""

import re
from pathlib import Path
from typing import Dict, Any

from .base_asset import BaseAsset
from .utils import generate_uuid, create_dummy_png, ensure_directory
from .naming_config import get_config


class ScriptAsset(BaseAsset):
    """GameMaker Script asset."""
    
    kind = "script"
    folder_prefix = "scripts"
    gm_tag = "GMScript"
    
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        return {
            "$GMScript": "v1",
            "%Name": name,
            "isCompatibility": False,
            "isDnD": False,
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "resourceType": "GMScript",
            "resourceVersion": "2.0"
        }
    
    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        gml_path = asset_folder / f"{name}.gml"
        if not gml_path.exists():
            is_constructor = kwargs.get('is_constructor', False)
            
            if is_constructor:
                gml_content = f"""/// @function {name}
/// @description Constructor for {name}
/// @returns {{struct}} {name} instance
function {name}() constructor {{
    // TODO: Add constructor properties and methods
    
    // Example static method:
    // static myMethod = function() {{
    //     // Method implementation
    // }}
}}
"""
            else:
                gml_content = f"""/// {name}()
/// Auto-generated stub. Replace with real code.
function {name}() {{
    // TODO
}}
"""
            gml_path.write_text(gml_content, encoding="utf-8")
            print(f"Created {gml_path.name}")
    
    def validate_name(self, name: str) -> bool:
        """Validate script name against configured pattern."""
        if not name:
            return False
        config = get_config()
        if not config.naming_enabled:
            return True  # Skip validation if disabled
        rule = config.get_rule("script")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class ObjectAsset(BaseAsset):
    """GameMaker Object asset."""
    
    kind = "object"
    folder_prefix = "objects"
    gm_tag = "GMObject"
    
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        sprite_id = kwargs.get("sprite_id", None)
        sprite_ref = None
        if sprite_id:
            sprite_ref = {
                "name": sprite_id,
                "path": f"sprites/{sprite_id.lower()}/{sprite_id}.yy"
            }
        
        # Handle parent object inheritance
        parent_object = kwargs.get("parent_object", None)
        parent_object_ref = None
        if parent_object:
            # Validate that parent_object is just the object name, not a full path
            if "/" in parent_object or "\\" in parent_object or parent_object.endswith(".yy"):
                raise ValueError(
                    f"ERROR: --parent-object parameter expects ONLY the object name, not a file path.\n"
                    f"You provided: '{parent_object}'\n"
                    f"Correct usage: --parent-object \"o_actor\" (just the object name)\n"
                    f"WRONG usage: --parent-object \"objects/o_actor/o_actor.yy\" (full path)"
                )
            
            parent_object_ref = {
                "name": parent_object,
                "path": f"objects/{parent_object.lower()}/{parent_object}.yy"
            }
        
        return {
            "$GMObject": "v1",
            "%Name": name,
            "eventList": [],
            "managed": True,
            "name": name,
            "overriddenProperties": [],
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "parentObjectId": parent_object_ref,
            "persistent": False,
            "physicsAngularDamping": 0.1,
            "physicsDensity": 0.5,
            "physicsFriction": 0.2,
            "physicsGroup": 0,
            "physicsKinematic": False,
            "physicsLinearDamping": 0.1,
            "physicsObject": False,
            "physicsRestitution": 0.1,
            "physicsSensor": False,
            "physicsShape": 1,
            "physicsShapePoints": [],
            "physicsStartAwake": True,
            "properties": [],
            "resourceType": "GMObject",
            "resourceVersion": "2.0",
            "solid": False,
            "spriteId": sprite_ref,
            "spriteMaskId": None,
            "visible": True
        }
    
    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        if kwargs.get("create_event", True):
            create_path = asset_folder / "Create_0.gml"
            if not create_path.exists():
                create_content = f"""/// Create Event for {name}
// Initialize variables here
"""
                create_path.write_text(create_content, encoding="utf-8")
                print(f"Created {create_path.name}")
    
    def validate_name(self, name: str) -> bool:
        """Validate object name against configured pattern."""
        if not super().validate_name(name):
            return False
        config = get_config()
        if not config.naming_enabled:
            return True
        rule = config.get_rule("object")
        if not rule:
            return True
        pattern = rule.get("pattern")
        if not pattern:
            return True
        return bool(re.match(pattern, name))


class SpriteAsset(BaseAsset):
    """GameMaker Sprite asset."""
    
    kind = "sprite"
    folder_prefix = "sprites"
    gm_tag = "GMSprite"
    
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        layer_uuid = generate_uuid()
        image_uuid = generate_uuid()
        
        return {
            "$GMSprite": "",
            "%Name": name,
            "bboxMode": 0,
            "bbox_bottom": 0,
            "bbox_left": 0,
            "bbox_right": 0,
            "bbox_top": 0,
            "collisionKind": 1,
            "collisionTolerance": 0,
            "DynamicTexturePage": False,
            "edgeFiltering": False,
            "For3D": False,
            "frames": [
                {
                    "$GMSpriteFrame": "",
                    "%Name": image_uuid,
                    "name": image_uuid,
                    "resourceType": "GMSpriteFrame",
                    "resourceVersion": "2.0"
                }
            ],
            "gridX": 0,
            "gridY": 0,
            "height": 1,
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
                    "visible": True
                }
            ],
            "name": name,
            "nineSlice": None,
            "origin": 0,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
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
                    "Keyframes": []
                },
                "eventStubScript": None,
                "eventToFunction": {},
                "length": 1.0,
                "lockOrigin": False,
                "moments": {
                    "resourceType": "KeyframeStore<MomentsEventKeyframe>",
                    "resourceVersion": "2.0",
                    "Keyframes": []
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
                            "Keyframes": [
                                {
                                    "$Keyframe<SpriteFrameKeyframe>": "",
                                    "Channels": {
                                        "0": {
                                            "$SpriteFrameKeyframe": "",
                                            "Id": {
                                                "name": image_uuid,
                                                "path": f"sprites/{name.lower()}/{name}.yy"
                                            },
                                            "resourceType": "SpriteFrameKeyframe",
                                            "resourceVersion": "2.0"
                                        }
                                    },
                                    "Disabled": False,
                                    "id": generate_uuid(),
                                    "IsCreationKey": False,
                                    "Key": 0.0,
                                    "Length": 1.0,
                                    "resourceType": "Keyframe<SpriteFrameKeyframe>",
                                    "resourceVersion": "2.0",
                                    "Stretch": False
                                }
                            ]
                        },
                        "modifiers": [],
                        "name": "frames",
                        "resourceType": "GMSpriteFramesTrack",
                        "resourceVersion": "2.0",
                        "spriteId": None,
                        "trackColour": 0,
                        "tracks": [],
                        "traits": 0
                    }
                ],
                "visibleRange": None,
                "volume": 1.0,
                "xorigin": 0,
                "yorigin": 0
            },
            "swatchColours": None,
            "swfPrecision": 2.525,
            "textureGroupId": {
                "name": "Default",
                "path": "texturegroups/Default"
            },
            "type": 0,
            "VTile": False,
            "width": 1
        }
    
    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Get UUIDs from the .yy data we just created
        yy_path = asset_folder / f"{name}.yy"
        if yy_path.exists():
            try:
                from .utils import load_json_loose
            except ImportError:
                from .utils import load_json_loose
            yy_data = load_json_loose(yy_path)
            
            # Extract UUIDs
            layer_uuid = yy_data["layers"][0]["name"]
            image_uuid = yy_data["frames"][0]["name"]
            
            # Create main image
            main_image_path = asset_folder / f"{image_uuid}.png"
            if not main_image_path.exists():
                create_dummy_png(main_image_path)
                print(f"Created {main_image_path.name} (dummy image)")
            
            # Create layer directory and image
            # NOTE: Directory structure should be layers/[frame_uuid]/[layer_uuid].png
            layer_dir = asset_folder / "layers" / image_uuid
            ensure_directory(layer_dir)
            
            layer_image_path = layer_dir / f"{layer_uuid}.png"
            if not layer_image_path.exists():
                create_dummy_png(layer_image_path)
                print(f"Created layers/{image_uuid}/{layer_uuid}.png (dummy image)")
            
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
                    "visible": True
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
                    "y": 0
                }
            ],
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "parentRoom": None,
            "physicsSettings": {
                "inheritPhysicsSettings": False,
                "PhysicsWorld": False,
                "PhysicsWorldGravityX": 0.0,
                "PhysicsWorldGravityY": 10.0,
                "PhysicsWorldPixToMetres": 0.1
            },
            "resourceType": "GMRoom",
            "resourceVersion": "2.0",
            "roomSettings": {
                "Height": height,
                "inheritRoomSettings": False,
                "persistent": False,
                "Width": width
            },
            "sequenceId": None,
            "views": [_view_template.copy() for _ in range(8)],
            "viewSettings": {
                "clearDisplayBuffer": True,
                "clearViewBackground": False,
                "enableViews": False,
                "inheritViewSettings": False
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
        elif parent_path.rstrip().endswith('.yy'):
            # Check if parent_path already contains the target name (full path provided)
            if parent_path.rstrip().endswith(f"/{name}.yy"):
                # Full target path provided, use as-is
                folder_path = parent_path.rstrip()
            else:
                # For parent_path like "folders/UI.yy", create nested path "folders/UI/name.yy"
                parent_dir = parent_path.rstrip().rstrip('.yy')
                folder_path = f"{parent_dir}/{name}.yy"
        else:
            # Treat as logical directory path
            clean_parent = parent_path.rstrip('/')
            if not clean_parent:
                clean_parent = 'folders'
            folder_path = f"{clean_parent}/{name}.yy"
        
        return {
            "$GMFolder": "",
            "%Name": name,
            "folderPath": folder_path,
            "name": name,
            "resourceType": "GMFolder",
            "resourceVersion": "2.0"
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
            from .utils import load_json_loose, save_pretty_json, insert_into_folders
        except ImportError:
            from .utils import load_json_loose, save_pretty_json, insert_into_folders
            
        # Determine the folder path for the .yyp entry
        if not parent_path:
            folder_path = f"folders/{name}.yy"
        elif parent_path.rstrip().endswith('.yy'):
            # Check if parent_path already contains the target name (full path provided)
            if parent_path.rstrip().endswith(f"/{name}.yy"):
                # Full target path provided, use as-is
                folder_path = parent_path.rstrip()
            else:
                # For parent_path like "folders/UI.yy", create nested path "folders/UI/name.yy"
                parent_dir = parent_path.rstrip().rstrip('.yy')
                folder_path = f"{parent_dir}/{name}.yy"
        else:
            # Treat as logical directory path
            clean_parent = parent_path.rstrip('/')
            if not clean_parent:
                clean_parent = 'folders'
            folder_path = f"{clean_parent}/{name}.yy"
        
        # Load the .yyp file
        from pathlib import Path
        yyp_files = list(project_root.glob("*.yyp"))
        if not yyp_files:
            raise FileNotFoundError("No .yyp file found in project root")
            
        yyp_file = yyp_files[0]
        project_data = load_json_loose(yyp_file)
        
        # Add folder to the Folders section
        folders = project_data.get("Folders", [])
        success = insert_into_folders(folders, name, folder_path)
        
        if success:
            project_data["Folders"] = folders
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
            "ConfigValues": {
                "desktop": {
                    "textureGroupId": "{ \"name\":\"fonts\", \"path\":\"texturegroups/fonts\" }"
                }
            },
            "first": 0,
            "fontName": font_name,
            "glyphOperations": 0,
            "glyphs": {
                "32": {"character": 32, "h": int(size * 2.5), "offset": 0, "shift": int(size * 0.4), "w": int(size * 0.4), "x": 2, "y": 2}
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
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "pointRounding": 0,
            "ranges": [
                {"lower": 32, "upper": 127},
                {"lower": 9647, "upper": 9647}
            ],
            "regenerateBitmap": False,
            "resourceType": "GMFont",
            "resourceVersion": "2.0",
            "sampleText": "abcdef ABCDEF\\n0123456789 .,<>\"'&!?\\nthe quick brown fox jumps over the lazy dog\\nTHE QUICK BROWN FOX JUMPS OVER THE LAZY DOG\\nDefault character: ▯ (9647)",
            "sdfSpread": 8,
            "size": float(size),
            "styleName": "Regular",
            "textureGroupId": {
                "name": "Default",
                "path": "texturegroups/Default"
            },
            "TTFName": "",
            "usesSDF": kwargs.get("uses_sdf", True)
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
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "resourceType": "GMShader",
            "resourceVersion": "2.0",
            "type": shader_type
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
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0}
            ]
        elif curve_type == "ease_in":
            points = [
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.0, "y": 0.0},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.15, "y": 0.03},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.5, "y": 0.25},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0}
            ]
        elif curve_type == "ease_out":
            points = [
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.0, "y": 0.0},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.5, "y": 0.75},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.85, "y": 0.97},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0}
            ]
        else:  # linear
            points = [
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 0.0, "y": 0.0},
                {"th0": 1.0, "th1": -1.0, "tv0": 0.0, "tv1": 0.0, "x": 1.0, "y": 1.0}
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
                    "visible": True
                }
            ],
            "function": kwargs.get("function", 1),  # 0=linear, 1=smooth
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "resourceType": "GMAnimCurve",
            "resourceVersion": "2.0"
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


class SoundAsset(BaseAsset):
    """GameMaker Sound asset."""
    
    kind = "sound"
    folder_prefix = "sounds"
    gm_tag = "GMSound"
    
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Sound configuration parameters
        volume = kwargs.get("volume", 1.0)
        pitch = kwargs.get("pitch", 1.0)
        sound_type = kwargs.get("sound_type", 0)  # 0=normal, 1=background, 2=3D
        bitrate = kwargs.get("bitrate", 128)
        sample_rate = kwargs.get("sample_rate", 44100)
        sound_format = kwargs.get("format", 0)  # 0=OGG, 1=MP3, 2=WAV
        
        return {
            "$GMSound": "",
            "%Name": name,
            "audioGroupId": {
                "name": "audiogroup_default",
                "path": "audiogroups/audiogroup_default"
            },
            "bitDepth": 1,
            "bitRate": bitrate,
            "compression": 0,
            "conversionMode": 0,
            "duration": 1.0,
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "preload": False,
            "resourceType": "GMSound",
            "resourceVersion": "2.0",
            "sampleRate": sample_rate,
            "soundFile": f"{name}.ogg",
            "type": sound_type,
            "volume": volume
        }
    
    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Create a dummy OGG file (placeholder)
        ogg_path = asset_folder / f"{name}.ogg"
        if not ogg_path.exists():
            # Create a minimal empty OGG file (placeholder)
            placeholder_content = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00"  # Minimal OGG header
            ogg_path.write_bytes(placeholder_content)
            print(f"Created {ogg_path.name} (placeholder audio file)")
            print(f"[WARN]  Replace with actual audio file (.ogg, .mp3, or .wav) before using!")
    
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
                {"speed": 100.0, "x": 300.0, "y": -50.0}
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
                {"speed": 100.0, "x": 200.0, "y": 0.0}
            ]
        
        return {
            "$GMPath": "",
            "%Name": name,
            "closed": closed,
            "kind": 1 if path_type == "smooth" else 0,  # 0=straight lines, 1=smooth curve
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "points": points,
            "precision": precision,
            "resourceType": "GMPath",
            "resourceVersion": "2.0"
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
            sprite_ref = {
                "name": sprite_id,
                "path": f"sprites/{sprite_id}/{sprite_id}.yy"
            }
        
        return {
            "$GMTileSet": "v1",
            "%Name": name,
            "autoTileSets": [],
            "macroPageTiles": {
                "SerialiseHeight": 0,
                "SerialiseWidth": 0,
                "TileSerialiseData": []
            },
            "name": name,
            "out_columns": int(256 / tile_width),  # Reasonable default
            "out_tilehborder": tile_xsep,
            "out_tilevborder": tile_ysep,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "resourceType": "GMTileSet",
            "resourceVersion": "2.0",
            "spriteId": sprite_ref,
            "spriteNoExport": True,
            "textureGroupId": {
                "name": "Default",
                "path": "texturegroups/Default"
            },
            "tileAnimationFrames": [],
            "tileAnimationSpeed": 15.0,
            "tileHeight": tile_height,
            "tilehsep": tile_xsep,
            "tilevsep": tile_ysep,
            "tileWidth": tile_width,
            "tilexoff": tile_xoff,
            "tileyoff": tile_yoff,
            "tile_count": 1
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
    
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Timeline configuration parameters - create a simple example timeline
        moments = kwargs.get("moments", [])
        
        # If no moments provided, create a basic example
        if not moments:
            moments = [
                {
                    "moment": 0,
                    "evnt": {
                        "isDnD": False,
                        "eventNum": 0,
                        "eventType": 0,
                        "collisionObjectId": None,
                        "resourceType": "GMEvent",
                        "resourceVersion": "2.0"
                    }
                }
            ]
        
        return {
            "$GMTimeline": "v1",
            "%Name": name,
            "momentList": moments,
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "resourceType": "GMTimeline",
            "resourceVersion": "2.0"
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
                "Keyframes": []
            },
            "eventStubScript": None,
            "eventToFunction": {},
            "length": length,
            "lockOrigin": False,
            "moments": {
                "resourceType": "KeyframeStore<MomentsEventKeyframe>",
                "resourceVersion": "2.0",
                "Keyframes": []
            },
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
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
            "yorigin": 0
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


class NoteAsset(BaseAsset):
    """GameMaker Note asset."""
    
    kind = "note"
    folder_prefix = "notes"
    gm_tag = "GMNotes"
    
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        # Note configuration parameters
        # NOTE: content is stored in the companion .txt file; keep kwargs handling here for consistency,
        # and ensure None does not propagate to file writes.
        _ = (kwargs.get("content") or f"# {name}\n\nThis is a note created by the CLI helper tools.\n\nAdd your documentation here.")
        
        return {
            "$GMNotes": "",
            "%Name": name,
            "name": name,
            "parent": {
                "name": self.get_parent_name(parent_path),
                "path": parent_path
            },
            "resourceType": "GMNotes",
            "resourceVersion": "2.0"
        }
    
    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        # Create the note content file
        note_path = asset_folder / f"{name}.txt"
        if not note_path.exists():
            content = kwargs.get("content") or f"# {name}\n\nThis is a note created by the CLI helper tools.\n\nAdd your documentation here."
            note_path.write_text(content, encoding="utf-8")
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


# Registry of asset handler singletons (exported for other modules)
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
