from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from ..base_asset import BaseAsset
from ..event_model import build_event_entry, parse_event_spec
from ..utils import atomic_write_text
from .naming import get_config


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
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
            "resourceType": "GMScript",
            "resourceVersion": "2.0",
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        gml_path = asset_folder / f"{name}.gml"
        if not gml_path.exists():
            is_constructor = kwargs.get("is_constructor", False)

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
            atomic_write_text(gml_path, gml_content)
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
            sprite_ref = {"name": sprite_id, "path": f"sprites/{sprite_id.lower()}/{sprite_id}.yy"}

        # Handle parent object inheritance
        parent_object = kwargs.get("parent_object", None)
        parent_object_ref = None
        if parent_object:
            # Validate that parent_object is just the object name, not a full path
            if "/" in parent_object or "\\" in parent_object or parent_object.endswith(".yy"):
                raise ValueError(
                    f"ERROR: --parent-object parameter expects ONLY the object name, not a file path.\n"
                    f"You provided: '{parent_object}'\n"
                    f'Correct usage: --parent-object "o_actor" (just the object name)\n'
                    f'WRONG usage: --parent-object "objects/o_actor/o_actor.yy" (full path)'
                )

            parent_object_ref = {"name": parent_object, "path": f"objects/{parent_object.lower()}/{parent_object}.yy"}

        event_list = [build_event_entry(parse_event_spec("create"))] if kwargs.get("create_event", True) else []

        return {
            "$GMObject": "",
            "%Name": name,
            "eventList": event_list,
            "managed": True,
            "name": name,
            "overriddenProperties": [],
            "parent": {"name": self.get_parent_name(parent_path), "path": parent_path},
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
            "visible": True,
        }

    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        if kwargs.get("create_event", True):
            create_path = asset_folder / "Create_0.gml"
            if not create_path.exists():
                create_content = f"""/// Create Event for {name}
// Initialize variables here
"""
                atomic_write_text(create_path, create_content)
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
