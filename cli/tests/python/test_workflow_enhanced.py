#!/usr/bin/env python3
"""
Enhanced Workflow Tests - Catches Critical Reference Issues
===========================================================

These tests would have caught the issues identified during social tab implementation:
1. Incomplete asset renaming (stale internal references)
2. Missing reference scanning
3. Sprite sequence/keyframe reference failures
"""

import os
import shutil
import tempfile
import json
from pathlib import Path
import unittest

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to the path
import sys

SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import from the correct locations
from gms_helpers.workflow import duplicate_asset, rename_asset, delete_asset
from gms_helpers.reference_scanner import (
    ReferenceScanner,
    comprehensive_rename_asset,
    find_gml_ambiguous_asset_bindings,
)
from gms_helpers.utils import save_pretty_json_gm, load_json_loose
from gms_helpers.assets import ObjectAsset, ScriptAsset, ShaderAsset, SpriteAsset
from gms_helpers.event_helper import add_event
from gms_helpers.exceptions import ValidationError

# Reference scanner should now work via the fallback import in workflow.py


class TempProject:
    """Enhanced test project with realistic GameMaker structure"""

    def __enter__(self):
        self.original_cwd = os.getcwd()
        self.dir = Path(tempfile.mkdtemp())

        # Build realistic project structure
        for f in ["scripts", "objects", "sprites", "rooms", "folders"]:
            (self.dir / f).mkdir()

        # Create realistic .yyp with resources
        self.yyp_data = {
            "$GMProject": "",
            "resources": [],
            "folders": [],
        }
        save_pretty_json_gm(self.dir / "test.yyp", self.yyp_data)

        # Create resource order file
        self.resource_order_data = {"FolderOrderSettings": [], "ResourceOrderSettings": []}
        save_pretty_json_gm(self.dir / "test.resource_order", self.resource_order_data)

        os.chdir(self.dir)
        return self

    def __exit__(self, exc_type, exc, tb):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.dir)

    def create_sprite_with_sequences(self, sprite_name: str):
        """Create a sprite with internal sequences (realistic GameMaker structure)"""
        sprite_dir = self.dir / "sprites" / sprite_name
        sprite_dir.mkdir(parents=True)

        # Create sprite .yy with internal sequences/keyframes
        sprite_data = {
            "$GMSprite": "",
            "%Name": sprite_name,
            "name": sprite_name,
            "sequence": {
                "$GMSequence": "",
                "%Name": sprite_name,  # This should update during rename!
                "name": sprite_name,  # This should update during rename!
                "spriteId": {
                    "name": sprite_name,
                    "path": f"sprites/{sprite_name}/{sprite_name}.yy",
                },
                "keyframes": {
                    "$KeyframeStore": "",
                    "keyframes": [
                        {
                            "id": "12345678-1234-5678-9012-123456789012",
                            "Key": 0.0,
                            "channels": {
                                "0": {
                                    "resourceType": "SpriteFrameKeyframe",
                                    "resourceVersion": "2.0",
                                    "Id": {
                                        "name": "frame_0",
                                        "path": f"sprites/{sprite_name}/frame_0.png",  # Path should update!
                                    },
                                }
                            },
                        }
                    ],
                },
            },
            "parent": {
                "name": "Sprites",
                "path": "folders/Sprites.yy",
            },
            "resourceType": "GMSprite",
            "resourceVersion": "2.0",
        }

        sprite_yy = sprite_dir / f"{sprite_name}.yy"
        save_pretty_json_gm(sprite_yy, sprite_data)

        # Add to project files
        self.add_resource_to_project(sprite_name, f"sprites/{sprite_name}/{sprite_name}.yy")
        return sprite_yy

    def create_script_with_asset_references(self, script_name: str, referenced_assets: list):
        """Create a script that references other assets"""
        script_dir = self.dir / "scripts" / script_name
        script_dir.mkdir(parents=True)

        # Create script .gml with asset references
        script_content = f"function {script_name}() {{\n"
        for asset in referenced_assets:
            if asset.startswith("o_"):
                script_content += f"    var obj = {asset};\n"
            elif asset.startswith("spr_"):
                script_content += f"    sprite_index = {asset};\n"
            elif asset.startswith("TestEnum."):
                script_content += f"    test_enum_set({asset}, id);\n"
        script_content += "}"

        script_gml = script_dir / f"{script_name}.gml"
        script_gml.write_text(script_content)

        # Create script .yy
        script_data = {
            "$GMScript": "",
            "%Name": script_name,
            "name": script_name,
            "parent": {
                "name": "Scripts",
                "path": "folders/Scripts.yy",
            },
            "resourceType": "GMScript",
            "resourceVersion": "2.0",
        }

        script_yy = script_dir / f"{script_name}.yy"
        save_pretty_json_gm(script_yy, script_data)

        self.add_resource_to_project(script_name, f"scripts/{script_name}/{script_name}.yy")
        return script_yy, script_gml

    def add_resource_to_project(self, name: str, path: str):
        """Add resource to .yyp and .resource_order files"""
        # Add to .yyp
        resource_entry = {"id": {"name": name, "path": path}}
        self.yyp_data["resources"].append(resource_entry)
        save_pretty_json_gm(self.dir / "test.yyp", self.yyp_data)

        # Add to resource order
        order_entry = {"name": name, "order": len(self.resource_order_data["ResourceOrderSettings"]), "path": path}
        self.resource_order_data["ResourceOrderSettings"].append(order_entry)
        save_pretty_json_gm(self.dir / "test.resource_order", self.resource_order_data)


class TestWorkflowEnhanced(unittest.TestCase):
    """Enhanced workflow tests that catch reference update issues"""

    def test_sprite_rename_updates_internal_sequences(self):
        """
        CRITICAL TEST: Sprite renaming must update internal sequence names and keyframe paths
        This test would have caught the sprite reference issue from social tab implementation
        """
        with TempProject() as proj:
            old_name = "spr_test_old"
            new_name = "spr_test_new"

            # Create sprite
            sprite_yy = proj.create_sprite_with_sequences(old_name)

            # Verify initial state
            sprite_data = load_json_loose(sprite_yy)
            self.assertEqual(sprite_data["sequence"]["%Name"], old_name)
            self.assertEqual(sprite_data["sequence"]["name"], old_name)
            self.assertIn(old_name, sprite_data["sequence"]["keyframes"]["keyframes"][0]["channels"]["0"]["Id"]["path"])

            # Rename the sprite using the full workflow function
            rename_asset(proj.dir, f"sprites/{old_name}/{old_name}.yy", new_name)

            # CRITICAL: Check that internal sequences were updated
            renamed_sprite_yy = proj.dir / "sprites" / new_name / f"{new_name}.yy"
            sprite_data = load_json_loose(renamed_sprite_yy)

            # These should be updated by the reference scanner
            self.assertEqual(
                sprite_data["sequence"]["%Name"],
                new_name,
                "Sprite sequence %Name was not updated - reference scanner failed!",
            )
            self.assertEqual(
                sprite_data["sequence"]["name"],
                new_name,
                "Sprite sequence name was not updated - reference scanner failed!",
            )

            # Keyframe paths should be updated
            keyframe_path = sprite_data["sequence"]["keyframes"]["keyframes"][0]["channels"]["0"]["Id"]["path"]
            self.assertIn(new_name, keyframe_path, "Sprite keyframe path was not updated - reference scanner failed!")
            self.assertNotIn(old_name, keyframe_path, "Sprite keyframe path still contains old name - stale reference!")

    def test_asset_rename_updates_script_references(self):
        """
        CRITICAL TEST: Asset renaming must update script references
        This test would have caught script reference issues
        """
        with TempProject() as proj:
            # Create object and script that references it
            old_object_name = "o_test_old"
            new_object_name = "o_test_new"

            # Create object
            object_asset = ObjectAsset()
            object_asset.create_files(proj.dir, old_object_name, "")
            proj.add_resource_to_project(old_object_name, f"objects/{old_object_name}/{old_object_name}.yy")

            # Create script that references the object
            script_yy, script_gml = proj.create_script_with_asset_references(
                "ui_test_script", [old_object_name, "TestEnum.test_old"]
            )

            # Verify initial script content
            script_content = script_gml.read_text()
            self.assertIn(old_object_name, script_content)
            self.assertIn("TestEnum.test_old", script_content)

            # Rename the object using the full workflow function
            rename_asset(proj.dir, f"objects/{old_object_name}/{old_object_name}.yy", new_object_name)

            # CRITICAL: Check that script references were updated
            updated_script_content = script_gml.read_text()

            # Object reference should be updated
            self.assertIn(
                new_object_name,
                updated_script_content,
                "Script object reference was not updated - reference scanner failed!",
            )
            self.assertNotIn(
                old_object_name, updated_script_content, "Script still contains old object reference - stale reference!"
            )

            # Unrelated identifiers that merely resemble the asset suffix stay unchanged.
            self.assertIn("TestEnum.test_old", updated_script_content)
            self.assertNotIn("TestEnum.test_new", updated_script_content)

    def test_script_rename_updates_object_event_callers(self):
        """Script renames must update GML callers in object event files."""
        with TempProject() as proj:
            old_script_name = "scr_agent_proof"
            new_script_name = "scr_agent_proof_renamed"

            script_yy, _script_gml = proj.create_script_with_asset_references(old_script_name, [])
            object_asset = ObjectAsset()
            object_asset.create_files(proj.dir, "o_agent_probe", "")
            proj.add_resource_to_project("o_agent_probe", "objects/o_agent_probe/o_agent_probe.yy")

            event_gml = proj.dir / "objects" / "o_agent_probe" / "Create_0.gml"
            event_gml.write_text(f"proof_value = {old_script_name}();\n", encoding="utf-8")

            rename_asset(proj.dir, f"scripts/{old_script_name}/{old_script_name}.yy", new_script_name)

            updated_event = event_gml.read_text(encoding="utf-8")
            self.assertIn(f"{new_script_name}()", updated_event)
            self.assertNotIn(f"{old_script_name}()", updated_event)

    def test_asset_rename_blocks_ambiguous_gml_bindings_before_mutation(self):
        with TempProject() as proj:
            old_name = "o_shadowed_asset"
            new_name = "o_renamed_asset"
            ObjectAsset().create_files(proj.dir, old_name, "")
            proj.add_resource_to_project(old_name, f"objects/{old_name}/{old_name}.yy")
            _script_yy, script_gml = proj.create_script_with_asset_references("scr_shadow_probe", [])
            original = f"var {old_name} = 3;\n{old_name} += 1;\nfunction probe({old_name}) {{ return {old_name}; }}\n"
            script_gml.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "Rename blocked.*ambiguous"):
                rename_asset(proj.dir, f"objects/{old_name}/{old_name}.yy", new_name)

            self.assertTrue((proj.dir / "objects" / old_name / f"{old_name}.yy").is_file())
            self.assertFalse((proj.dir / "objects" / new_name).exists())
            self.assertEqual(script_gml.read_text(encoding="utf-8"), original)

    def test_collision_target_rename_updates_all_event_metadata_and_files(self):
        with TempProject() as proj:
            old_name = "o_collision_target"
            new_name = "o_collision_renamed"
            owners = [old_name, "o_collision_owner_a", "o_collision_owner_b"]
            for owner in owners:
                ObjectAsset().create_files(proj.dir, owner, "")
                proj.add_resource_to_project(owner, f"objects/{owner}/{owner}.yy")
            for owner in owners:
                add_event(owner, f"collision:{old_name}", f"hit = {old_name};\n", proj.dir)

            rename_asset(proj.dir, f"objects/{old_name}/{old_name}.yy", new_name)

            for original_owner in owners:
                owner = new_name if original_owner == old_name else original_owner
                owner_dir = proj.dir / "objects" / owner
                self.assertFalse((owner_dir / f"Collision_{old_name}.gml").exists())
                self.assertTrue((owner_dir / f"Collision_{new_name}.gml").is_file())
                owner_data = load_json_loose(owner_dir / f"{owner}.yy")
                collision = next(event for event in owner_data["eventList"] if event["eventType"] == 4)
                self.assertEqual(collision["eventNum"], 0)
                self.assertEqual(collision["%Name"], f"Collision_{new_name}")
                self.assertEqual(collision["name"], f"Collision_{new_name}")
                self.assertEqual(
                    collision["collisionObjectId"],
                    {"name": new_name, "path": f"objects/{new_name}/{new_name}.yy"},
                )

    def test_collision_target_rename_preflights_destination_conflict_before_mutation(self):
        with TempProject() as proj:
            old_name = "o_collision_target"
            new_name = "o_collision_renamed"
            for name in (old_name, "o_collision_owner"):
                ObjectAsset().create_files(proj.dir, name, "")
                proj.add_resource_to_project(name, f"objects/{name}/{name}.yy")
            add_event("o_collision_owner", f"collision:{old_name}", "hit = true;\n", proj.dir)
            owner_dir = proj.dir / "objects" / "o_collision_owner"
            (owner_dir / f"Collision_{new_name}.gml").write_text("conflict\n", encoding="utf-8")
            project_before = (proj.dir / "test.yyp").read_bytes()

            with self.assertRaises(ValidationError):
                rename_asset(proj.dir, f"objects/{old_name}/{old_name}.yy", new_name)

            self.assertTrue((proj.dir / "objects" / old_name / f"{old_name}.yy").is_file())
            self.assertFalse((proj.dir / "objects" / new_name).exists())
            self.assertEqual((proj.dir / "test.yyp").read_bytes(), project_before)

    def test_asset_rename_updates_resource_order(self):
        """
        CRITICAL TEST: Asset renaming must update resource order files
        This test would have caught resource order update issues
        """
        with TempProject() as proj:
            old_name = "spr_test_old"
            new_name = "spr_test_new"

            # Create sprite
            sprite_yy = proj.create_sprite_with_sequences(old_name)

            # Verify initial resource order
            resource_order_data = load_json_loose(proj.dir / "test.resource_order")
            old_entry = next(
                (entry for entry in resource_order_data["ResourceOrderSettings"] if entry["name"] == old_name), None
            )
            self.assertIsNotNone(old_entry, "Resource order entry not found")
            self.assertIn(old_name, old_entry["path"])

            # Rename the sprite using the full workflow function
            rename_asset(proj.dir, f"sprites/{old_name}/{old_name}.yy", new_name)

            # CRITICAL: Check that resource order was updated
            updated_resource_order = load_json_loose(proj.dir / "test.resource_order")

            # Old entry should be gone
            old_entry_after = next(
                (entry for entry in updated_resource_order["ResourceOrderSettings"] if entry["name"] == old_name), None
            )
            self.assertIsNone(old_entry_after, "Resource order still contains old entry - reference scanner failed!")

            # New entry should exist
            new_entry = next(
                (entry for entry in updated_resource_order["ResourceOrderSettings"] if entry["name"] == new_name), None
            )
            self.assertIsNotNone(new_entry, "Resource order does not contain new entry - reference scanner failed!")
            self.assertIn(new_name, new_entry["path"])
            self.assertNotIn(old_name, new_entry["path"])

    def test_reference_scanner_finds_all_references(self):
        """
        CRITICAL TEST: Reference scanner must find ALL references across project
        This test ensures comprehensive reference detection
        """
        with TempProject() as proj:
            old_name = "spr_test_asset"
            new_name = "spr_renamed_asset"

            # Create sprite with sequences
            sprite_yy = proj.create_sprite_with_sequences(old_name)

            # Create script that references the sprite
            script_yy, script_gml = proj.create_script_with_asset_references("test_script", [old_name])

            # Use reference scanner to find all references
            scanner = ReferenceScanner(proj.dir)
            references = scanner.find_all_asset_references(old_name, new_name, "sprite")

            # CRITICAL: Must find references in multiple file types
            reference_types = [ref.reference_type for ref in references]

            # Should find project file references
            self.assertIn(
                "project_resource_name", reference_types, "Reference scanner missed project resource name reference!"
            )
            self.assertIn(
                "project_resource_path", reference_types, "Reference scanner missed project resource path reference!"
            )

            # Should find resource order references
            self.assertIn("resource_order", reference_types, "Reference scanner missed resource order reference!")

            # Should find sprite internal references
            self.assertIn(
                "sprite_sequence_name", reference_types, "Reference scanner missed sprite sequence name reference!"
            )

            # Should find script references
            self.assertIn(
                "script_sprite_reference", reference_types, "Reference scanner missed script sprite reference!"
            )

            # Verify reference count is reasonable (multiple references expected)
            self.assertGreaterEqual(
                len(references), 4, f"Reference scanner found only {len(references)} references, expected at least 4!"
            )

    def test_comprehensive_rename_validates_no_stale_references(self):
        """
        CRITICAL TEST: After renaming, there should be NO stale references to old name
        This test ensures complete reference cleanup
        """
        with TempProject() as proj:
            old_name = "o_tab_friends"
            new_name = "o_tab_social"

            # Create object
            object_asset = ObjectAsset()
            object_asset.create_files(proj.dir, old_name, "")
            proj.add_resource_to_project(old_name, f"objects/{old_name}/{old_name}.yy")

            # Create script that references the object
            script_yy, script_gml = proj.create_script_with_asset_references(
                "ui_tab_test", [old_name, "UIGroup.tab_friends"]
            )

            # Use comprehensive rename (this includes validation)
            success = comprehensive_rename_asset(proj.dir, old_name, new_name, "object")

            # CRITICAL: Should return True (no stale references)
            self.assertTrue(success, "Comprehensive rename failed - stale references remain!")

            # Additional validation: manual check for stale references
            scanner = ReferenceScanner(proj.dir)
            stale_refs = scanner.validate_no_stale_references(old_name)

            self.assertEqual(
                len(stale_refs), 0, f"Found {len(stale_refs)} stale references after comprehensive rename: {stale_refs}"
            )

    def test_rename_changes_only_executable_gml_identifiers(self):
        with TempProject() as proj:
            old_name = "o_semantic_old"
            new_name = "o_semantic_new"
            object_asset = ObjectAsset()
            object_asset.create_files(proj.dir, old_name, "")
            proj.add_resource_to_project(old_name, f"objects/{old_name}/{old_name}.yy")
            _script_yy, script_gml = proj.create_script_with_asset_references("scr_semantic_probe", [])
            script_gml.write_text(
                f"var target = {old_name};\n"
                f"// keep comment {old_name}\n"
                f"/* keep block {old_name} */\n"
                f'var label = "keep string {old_name}";\n'
                f'var verbatim = @"keep verbatim {old_name}";\n'
                f"var longer = {old_name}_variant;\n",
                encoding="utf-8",
            )

            rename_asset(proj.dir, f"objects/{old_name}/{old_name}.yy", new_name)

            updated = script_gml.read_text(encoding="utf-8")
            self.assertIn(f"var target = {new_name};", updated)
            self.assertIn(f"// keep comment {old_name}", updated)
            self.assertIn(f"/* keep block {old_name} */", updated)
            self.assertIn(f'"keep string {old_name}"', updated)
            self.assertIn(f'@"keep verbatim {old_name}"', updated)
            self.assertIn(f"{old_name}_variant", updated)

    def test_rename_preserves_scoped_fields_and_struct_keys_named_like_asset(self):
        with TempProject() as proj:
            old_name = "o_scoped_old"
            new_name = "o_scoped_new"
            object_asset = ObjectAsset()
            object_asset.create_files(proj.dir, old_name, "")
            proj.add_resource_to_project(old_name, f"objects/{old_name}/{old_name}.yy")
            _script_yy, script_gml = proj.create_script_with_asset_references("scr_scoped_probe", [])
            script_gml.write_text(
                f"self.{old_name} = 1;\n"
                f"global.{old_name} += 1;\n"
                f"config /* keep */ . {old_name} = 2;\n"
                f"var values = {{ {old_name}: {old_name} }};\n"
                f"switch (target) {{ case {old_name}: break; }}\n"
                f"var choice = flag ? {old_name} : noone;\n"
                f"enum Kind {{ {old_name} = 7, other = {old_name} }}\n"
                f"#region {old_name}\n"
                f"var enum_value = {old_name};\n"
                f"#endregion {old_name}\n"
                f'var dynamic_asset = asset_get_index("{old_name}");\n'
                f'var verbatim_asset = asset_get_index(@"{old_name}");\n'
                f'var scoped_lookup = resolver.asset_get_index("{old_name}");\n'
                f'var ordinary_label = "{old_name}";\n'
                f"var target = {old_name};\n",
                encoding="utf-8",
            )

            rename_asset(proj.dir, f"objects/{old_name}/{old_name}.yy", new_name)

            updated = script_gml.read_text(encoding="utf-8")
            self.assertIn(f"self.{old_name} = 1;", updated)
            self.assertIn(f"global.{old_name} += 1;", updated)
            self.assertIn(f"config /* keep */ . {old_name} = 2;", updated)
            self.assertIn(f"{{ {old_name}: {new_name} }}", updated)
            self.assertIn(f"case {new_name}:", updated)
            self.assertIn(f"flag ? {new_name} : noone", updated)
            self.assertIn(f"enum Kind {{ {old_name} = 7, other = {new_name} }}", updated)
            self.assertIn(f"#region {old_name}", updated)
            self.assertIn(f"#endregion {old_name}", updated)
            self.assertIn(f"var enum_value = {new_name};", updated)
            self.assertIn(f'asset_get_index("{new_name}")', updated)
            self.assertIn(f'asset_get_index(@"{new_name}")', updated)
            self.assertIn(f'resolver.asset_get_index("{old_name}")', updated)
            self.assertIn(f'var ordinary_label = "{old_name}";', updated)
            self.assertIn(f"var target = {new_name};", updated)

    def test_rename_updates_exact_structured_paths_without_touching_unrelated_names(self):
        with TempProject() as proj:
            old_name = "o_structured_old"
            new_name = "o_structured_new"
            old_path = f"objects/{old_name}/{old_name}.yy"
            new_path = f"objects/{new_name}/{new_name}.yy"
            object_asset = ObjectAsset()
            object_asset.create_files(proj.dir, old_name, "")
            proj.add_resource_to_project(old_name, old_path)
            target_yy = proj.dir / old_path
            target_data = load_json_loose(target_yy)
            target_data["properties"] = [
                {
                    "$GMObjectProperty": "v2",
                    "%Name": old_name,
                    "name": old_name,
                    "resourceType": "GMObjectProperty",
                    "value": old_name,
                }
            ]
            save_pretty_json_gm(target_yy, target_data)

            holder_name = "o_structured_holder"
            holder_dir = proj.dir / "objects" / holder_name
            holder_dir.mkdir(parents=True)
            save_pretty_json_gm(
                holder_dir / f"{holder_name}.yy",
                {
                    "$GMObject": "",
                    "%Name": holder_name,
                    "name": holder_name,
                    "parentObjectId": {"name": old_name, "path": old_path},
                    "properties": [
                        {
                            "$GMObjectProperty": "v2",
                            "resourceType": "GMObjectProperty",
                            "value": old_name,
                        }
                    ],
                    "overriddenProperties": [
                        {
                            "$GMOverriddenProperty": "v1",
                            "resourceType": "GMOverriddenProperty",
                            "objectId": {"name": old_name, "path": old_path},
                            "propertyId": {"name": old_name, "path": old_path},
                            "value": "0",
                        }
                    ],
                    "unrelated": {"name": old_name, "path": "objects/o_other/o_other.yy"},
                },
            )
            proj.add_resource_to_project(holder_name, f"objects/{holder_name}/{holder_name}.yy")
            proj.yyp_data["resourceOrder"] = [old_path]
            save_pretty_json_gm(proj.dir / "test.yyp", proj.yyp_data)

            rename_asset(proj.dir, old_path, new_name)

            holder = load_json_loose(holder_dir / f"{holder_name}.yy")
            self.assertEqual(holder["parentObjectId"], {"name": new_name, "path": new_path})
            self.assertEqual(holder["properties"][0]["value"], new_name)
            self.assertEqual(holder["overriddenProperties"][0]["objectId"], {"name": new_name, "path": new_path})
            self.assertEqual(holder["overriddenProperties"][0]["propertyId"], {"name": old_name, "path": new_path})
            self.assertEqual(holder["unrelated"], {"name": old_name, "path": "objects/o_other/o_other.yy"})
            renamed_target = load_json_loose(proj.dir / new_path)
            self.assertEqual(renamed_target["properties"][0]["%Name"], old_name)
            self.assertEqual(renamed_target["properties"][0]["name"], old_name)
            self.assertEqual(renamed_target["properties"][0]["value"], new_name)
            project_data = load_json_loose(proj.dir / "test.yyp")
            self.assertEqual(project_data["resourceOrder"], [new_path])

    def test_room_rename_does_not_rename_nested_layer_with_same_name(self):
        with TempProject() as proj:
            old_name = "r_scoped_old"
            new_name = "r_scoped_new"
            old_path = f"rooms/{old_name}/{old_name}.yy"
            room_dir = proj.dir / "rooms" / old_name
            room_dir.mkdir(parents=True)
            save_pretty_json_gm(
                room_dir / f"{old_name}.yy",
                {
                    "$GMRoom": "",
                    "%Name": old_name,
                    "name": old_name,
                    "layers": [
                        {
                            "$GMRInstanceLayer": "",
                            "%Name": old_name,
                            "name": old_name,
                            "resourceType": "GMRInstanceLayer",
                        }
                    ],
                },
            )
            proj.add_resource_to_project(old_name, old_path)

            rename_asset(proj.dir, old_path, new_name)

            renamed = load_json_loose(proj.dir / "rooms" / new_name / f"{new_name}.yy")
            self.assertEqual(renamed["name"], new_name)
            self.assertEqual(renamed["%Name"], new_name)
            self.assertEqual(renamed["layers"][0]["name"], old_name)
            self.assertEqual(renamed["layers"][0]["%Name"], old_name)

    def test_room_duplicate_and_delete_keep_room_order_nodes_consistent(self):
        with TempProject() as proj:
            source_name = "r_order_source"
            copy_name = "r_order_copy"
            source_path = f"rooms/{source_name}/{source_name}.yy"
            source_dir = proj.dir / "rooms" / source_name
            source_dir.mkdir(parents=True)
            save_pretty_json_gm(
                source_dir / f"{source_name}.yy",
                {"$GMRoom": "", "%Name": source_name, "name": source_name},
            )
            proj.add_resource_to_project(source_name, source_path)
            project = load_json_loose(proj.dir / "test.yyp")
            project["RoomOrderNodes"] = [{"roomId": {"name": source_name, "path": source_path}}]
            save_pretty_json_gm(proj.dir / "test.yyp", project)

            duplicate_asset(proj.dir, source_path, copy_name)
            duplicated_project = load_json_loose(proj.dir / "test.yyp")
            self.assertEqual(
                [entry["roomId"]["name"] for entry in duplicated_project["RoomOrderNodes"]],
                [source_name, copy_name],
            )

            delete_asset(proj.dir, source_path, force=True)
            deleted_project = load_json_loose(proj.dir / "test.yyp")
            self.assertEqual(
                [entry["roomId"]["name"] for entry in deleted_project["RoomOrderNodes"]],
                [copy_name],
            )

    def test_duplicate_sprite_regenerates_local_identities_and_paths(self):
        with TempProject() as proj:
            old_name = "spr_identity_source"
            new_name = "spr_identity_copy"
            frame_id = "1" * 32
            layer_id = "2" * 32
            keyframe_id = "3" * 32
            sprite_dir = proj.dir / "sprites" / old_name
            (sprite_dir / "layers" / frame_id).mkdir(parents=True)
            (sprite_dir / f"{frame_id}.png").write_bytes(b"frame")
            (sprite_dir / "layers" / frame_id / f"{layer_id}.png").write_bytes(b"layer")
            save_pretty_json_gm(
                sprite_dir / f"{old_name}.yy",
                {
                    "$GMSprite": "",
                    "%Name": old_name,
                    "name": old_name,
                    "frames": [{"%Name": frame_id, "name": frame_id}],
                    "layers": [{"%Name": layer_id, "name": layer_id}],
                    "parent": {"name": "Sprites", "path": "folders/Sprites.yy"},
                    "sequence": {
                        "%Name": old_name,
                        "name": old_name,
                        "tracks": [
                            {
                                "keyframes": {
                                    "Keyframes": [
                                        {
                                            "id": keyframe_id,
                                            "Channels": {
                                                "0": {
                                                    "Id": {
                                                        "name": frame_id,
                                                        "path": f"sprites/{old_name}/{old_name}.yy",
                                                    }
                                                }
                                            },
                                        }
                                    ]
                                }
                            }
                        ],
                    },
                },
            )
            proj.add_resource_to_project(old_name, f"sprites/{old_name}/{old_name}.yy")
            proj.yyp_data["resourceOrder"] = [f"sprites/{old_name}/{old_name}.yy"]
            save_pretty_json_gm(proj.dir / "test.yyp", proj.yyp_data)

            duplicate_asset(proj.dir, f"sprites/{old_name}/{old_name}.yy", new_name)

            copied_dir = proj.dir / "sprites" / new_name
            copied = load_json_loose(copied_dir / f"{new_name}.yy")
            copied_frame = copied["frames"][0]["name"]
            copied_layer = copied["layers"][0]["name"]
            copied_keyframe = copied["sequence"]["tracks"][0]["keyframes"]["Keyframes"][0]
            self.assertNotEqual(copied_frame, frame_id)
            self.assertNotEqual(copied_layer, layer_id)
            self.assertNotEqual(copied_keyframe["id"], keyframe_id)
            self.assertEqual(copied_keyframe["Channels"]["0"]["Id"]["name"], copied_frame)
            self.assertEqual(
                copied_keyframe["Channels"]["0"]["Id"]["path"],
                f"sprites/{new_name}/{new_name}.yy",
            )
            self.assertTrue((copied_dir / f"{copied_frame}.png").exists())
            self.assertTrue((copied_dir / "layers" / copied_frame / f"{copied_layer}.png").exists())
            self.assertEqual(copied["parent"]["path"], "folders/Sprites.yy")
            order_data = load_json_loose(proj.dir / "test.resource_order")
            order_entries = order_data["ResourceOrderSettings"]
            self.assertEqual([entry["name"] for entry in order_entries], [old_name, new_name])
            self.assertEqual([entry["order"] for entry in order_entries], [0, 1])
            project_data = load_json_loose(proj.dir / "test.yyp")
            self.assertEqual(
                project_data["resourceOrder"],
                [
                    f"sprites/{old_name}/{old_name}.yy",
                    f"sprites/{new_name}/{new_name}.yy",
                ],
            )

    def test_duplicate_room_regenerates_instance_identity_and_preserves_object_reference(self):
        with TempProject() as proj:
            old_name = "r_identity_source"
            new_name = "r_identity_copy"
            instance_id = f"inst_{'4' * 32}"
            room_dir = proj.dir / "rooms" / old_name
            room_dir.mkdir(parents=True)
            creation_file = f"InstanceCreationCode_{instance_id}.gml"
            (room_dir / creation_file).write_text("hp = 10;\n", encoding="utf-8")
            save_pretty_json_gm(
                room_dir / f"{old_name}.yy",
                {
                    "$GMRoom": "",
                    "%Name": old_name,
                    "name": old_name,
                    "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
                    "instanceCreationOrder": [{"name": instance_id, "path": f"rooms/{old_name}/{old_name}.yy"}],
                    "layers": [
                        {
                            "$GMRInstanceLayer": "",
                            "name": "Instances",
                            "instances": [
                                {
                                    "$GMRInstance": "",
                                    "resourceType": "GMRInstance",
                                    "name": instance_id,
                                    "creationCodeFile": creation_file,
                                    "objectId": {
                                        "name": "o_enemy",
                                        "path": "objects/o_enemy/o_enemy.yy",
                                    },
                                }
                            ],
                        }
                    ],
                },
            )
            proj.add_resource_to_project(old_name, f"rooms/{old_name}/{old_name}.yy")

            duplicate_asset(proj.dir, f"rooms/{old_name}/{old_name}.yy", new_name)

            copied_dir = proj.dir / "rooms" / new_name
            copied = load_json_loose(copied_dir / f"{new_name}.yy")
            copied_instance = copied["layers"][0]["instances"][0]
            self.assertNotEqual(copied_instance["name"], instance_id)
            self.assertEqual(copied_instance["objectId"]["path"], "objects/o_enemy/o_enemy.yy")
            self.assertEqual(
                copied["instanceCreationOrder"][0]["path"],
                f"rooms/{new_name}/{new_name}.yy",
            )
            self.assertTrue((copied_dir / copied_instance["creationCodeFile"]).exists())

    def test_duplicate_script_preserves_parent_and_only_renames_executable_stub(self):
        with TempProject() as proj:
            old_name = "scr_copy_source"
            new_name = "scr_copy_target"
            script_dir = proj.dir / "scripts" / old_name
            script_dir.mkdir(parents=True)
            save_pretty_json_gm(
                script_dir / f"{old_name}.yy",
                {
                    "$GMScript": "",
                    "%Name": old_name,
                    "name": old_name,
                    "parent": {"name": "Scripts", "path": "folders/Scripts.yy"},
                },
            )
            (script_dir / f"{old_name}.gml").write_text(
                f"function {old_name}(value) {{\n"
                f"    // {old_name} stays in docs\n"
                f'    return value + string("{old_name}");\n'
                "}\n",
                encoding="utf-8",
            )
            proj.add_resource_to_project(old_name, f"scripts/{old_name}/{old_name}.yy")

            duplicate_asset(proj.dir, f"scripts/{old_name}/{old_name}.yy", new_name)

            copied_dir = proj.dir / "scripts" / new_name
            copied = load_json_loose(copied_dir / f"{new_name}.yy")
            copied_gml = (copied_dir / f"{new_name}.gml").read_text(encoding="utf-8")
            self.assertEqual(copied["parent"]["path"], "folders/Scripts.yy")
            self.assertIn(f"function {new_name}(value)", copied_gml)
            self.assertIn(f"// {old_name} stays in docs", copied_gml)
            self.assertIn(f'"{old_name}"', copied_gml)

    def test_duplicate_and_rename_shader_keep_source_filenames_aligned(self):
        with TempProject() as proj:
            old_name = "shd_source"
            copy_name = "shd_copy"
            renamed_name = "shd_renamed"
            shader = ShaderAsset()
            shader.create_files(proj.dir, old_name, "")
            old_path = f"shaders/{old_name}/{old_name}.yy"
            proj.add_resource_to_project(old_name, old_path)

            duplicate_asset(proj.dir, old_path, copy_name)
            copied_dir = proj.dir / "shaders" / copy_name
            self.assertTrue((copied_dir / f"{copy_name}.vsh").exists())
            self.assertTrue((copied_dir / f"{copy_name}.fsh").exists())
            self.assertFalse((copied_dir / f"{old_name}.vsh").exists())

            rename_asset(proj.dir, old_path, renamed_name)
            renamed_dir = proj.dir / "shaders" / renamed_name
            self.assertTrue((renamed_dir / f"{renamed_name}.vsh").exists())
            self.assertTrue((renamed_dir / f"{renamed_name}.fsh").exists())
            self.assertFalse((renamed_dir / f"{old_name}.fsh").exists())

    def test_delete_removes_structured_resource_order_entries(self):
        with TempProject() as proj:
            name = "scr_delete_ordered"
            path = f"scripts/{name}/{name}.yy"
            proj.create_script_with_asset_references(name, [])
            proj.yyp_data["resourceOrder"] = [path]
            save_pretty_json_gm(proj.dir / "test.yyp", proj.yyp_data)

            result = delete_asset(proj.dir, path, dry_run=False)

            self.assertTrue(result.success)
            project_data = load_json_loose(proj.dir / "test.yyp")
            self.assertEqual(project_data["resourceOrder"], [])
            order_data = load_json_loose(proj.dir / "test.resource_order")
            self.assertEqual(order_data["ResourceOrderSettings"], [])

    def test_sprite_creation_json_format(self):
        """Test that sprite creation generates valid JSON without extra fields"""
        with TempProject() as project:
            os.chdir(project.dir)

            # Create a sprite asset
            sprite_asset = SpriteAsset()
            sprite_name = "spr_test_button"
            parent_path = "folders/UI.yy"

            # Create the sprite
            sprite_asset.create_files(project.dir, sprite_name, parent_path)
            sprite_file = project.dir / "sprites" / sprite_name.lower() / f"{sprite_name}.yy"

            # Load and validate JSON structure
            sprite_data = load_json_loose(sprite_file)

            # Check that tracks array has correct format (no extra %Name field)
            tracks = sprite_data["sequence"]["tracks"]
            self.assertGreater(len(tracks), 0, "Sprite should have at least one track")

            track = tracks[0]
            self.assertIn("$GMSpriteFramesTrack", track, "Track should have correct type marker")
            self.assertIn("builtinName", track, "Track should have builtinName field")
            self.assertNotIn("%Name", track, "Track should NOT have %Name field - this causes JSON parsing errors!")

            # Verify required fields exist
            required_fields = [
                "builtinName",
                "events",
                "inheritsTrackColour",
                "interpolation",
                "isCreationTrack",
                "keyframes",
                "modifiers",
                "name",
                "resourceType",
                "resourceVersion",
                "spriteId",
                "trackColour",
                "tracks",
                "traits",
            ]
            for field in required_fields:
                self.assertIn(field, track, f"Track missing required field: {field}")

    def test_comprehensive_sprite_rename_catches_yy_filename_refs(self):
        """Test that sprite renaming catches internal .yy filename references"""
        with TempProject() as project:
            os.chdir(project.dir)

            old_name = "spr_old_button"
            new_name = "spr_new_button"

            # Create sprite with keyframe that references the .yy file
            sprite_dir = project.dir / "sprites" / old_name.lower()
            sprite_dir.mkdir(parents=True)

            # Create sprite .yy with internal keyframe path reference
            sprite_data = {
                "$GMSprite": "",
                "name": old_name,
                "sequence": {
                    "tracks": [
                        {
                            "$GMSpriteFramesTrack": "",
                            "keyframes": {
                                "Keyframes": [
                                    {
                                        "Channels": {
                                            "0": {
                                                "Id": {"name": "test-uuid", "path": f"sprites/{old_name}/{old_name}.yy"}
                                            }
                                        }
                                    }
                                ]
                            },
                        }
                    ]
                },
            }

            sprite_file = sprite_dir / f"{old_name}.yy"
            save_pretty_json_gm(sprite_file, sprite_data)

            # Test reference scanner catches the .yy filename reference
            scanner = ReferenceScanner(project.dir)
            references = scanner.find_all_asset_references(old_name, new_name, "sprite")

            # Should find the keyframe path reference (full path, not just filename)
            yy_path_refs = [ref for ref in references if ref.reference_type == "sprite_keyframe_path"]
            self.assertGreater(len(yy_path_refs), 0, "Reference scanner should find internal .yy path references!")

            # Verify it found the correct reference
            found_ref = yy_path_refs[0]
            self.assertIn(f"sprites/{old_name}/{old_name}.yy", found_ref.old_text)
            self.assertIn(f"sprites/{new_name}/{new_name}.yy", found_ref.new_text)

    def test_sprite_creation_layer_directory_structure(self):
        """Test that sprite creation generates correct layer directory structure"""
        with TempProject() as project:
            os.chdir(project.dir)

            # Create a sprite asset
            sprite_asset = SpriteAsset()
            sprite_name = "spr_test_layer_structure"
            parent_path = "folders/UI.yy"

            # Create the sprite
            sprite_asset.create_files(project.dir, sprite_name, parent_path)
            sprite_dir = project.dir / "sprites" / sprite_name.lower()
            sprite_file = sprite_dir / f"{sprite_name}.yy"

            # Load sprite data to get UUIDs
            sprite_data = load_json_loose(sprite_file)

            # Extract the expected UUIDs
            layer_uuid = sprite_data["layers"][0]["name"]
            image_uuid = sprite_data["frames"][0]["name"]

            # Verify correct directory structure: layers/[frame_uuid]/[layer_uuid].png
            expected_structure_path = sprite_dir / "layers" / image_uuid / f"{layer_uuid}.png"
            wrong_structure_path = sprite_dir / "layers" / layer_uuid / f"{image_uuid}.png"

            self.assertTrue(
                expected_structure_path.exists(),
                f"Layer image should exist at layers/{image_uuid}/{layer_uuid}.png (frame_uuid/layer_uuid.png)",
            )
            self.assertFalse(
                wrong_structure_path.exists(),
                f"Layer image should NOT exist at layers/{layer_uuid}/{image_uuid}.png (wrong structure)",
            )

            # Verify the main image also exists
            main_image_path = sprite_dir / f"{image_uuid}.png"
            self.assertTrue(main_image_path.exists(), "Main sprite image should exist")


class TestReferenceScanner(unittest.TestCase):
    """Dedicated tests for the reference scanner module"""

    def test_sprite_sequence_detection(self):
        """Test that sprite sequence references are properly detected"""
        with TempProject() as proj:
            sprite_name = "spr_test"
            sprite_yy = proj.create_sprite_with_sequences(sprite_name)

            scanner = ReferenceScanner(proj.dir)
            references = scanner.find_all_asset_references(sprite_name, "spr_new", "sprite")

            # Should find sequence name references
            sequence_refs = [ref for ref in references if ref.reference_type == "sprite_sequence_name"]
            self.assertGreater(len(sequence_refs), 0, "No sprite sequence name references found!")

            # Should find keyframe path references
            keyframe_refs = [ref for ref in references if ref.reference_type == "sprite_keyframe_path"]
            self.assertGreater(len(keyframe_refs), 0, "No sprite keyframe path references found!")

    def test_atomic_reference_updates(self):
        """Test that reference updates are atomic (all or nothing)"""
        with TempProject() as proj:
            old_name = "test_asset"
            new_name = "renamed_asset"

            # Create sprite
            sprite_yy = proj.create_sprite_with_sequences(old_name)

            scanner = ReferenceScanner(proj.dir)
            references = scanner.find_all_asset_references(old_name, new_name, "sprite")

            # Apply updates
            files_updated, total_updates = scanner.update_all_references(references)

            self.assertGreater(files_updated, 0, "No files were updated!")
            self.assertGreater(total_updates, 0, "No references were updated!")

            # Verify updates were applied
            sprite_data = load_json_loose(proj.dir / "sprites" / old_name / f"{old_name}.yy")
            self.assertEqual(
                sprite_data["sequence"]["%Name"], new_name, "Atomic update failed - sequence name not updated!"
            )

    def test_stale_reference_validation_ignores_new_names_containing_old_name(self):
        with TempProject() as proj:
            script_yy, script_gml = proj.create_script_with_asset_references("scr_agent_proof_renamed", [])
            script_gml.write_text(
                "function scr_agent_proof_renamed() {\n    return scr_agent_proof_renamed();\n}\n",
                encoding="utf-8",
            )

            scanner = ReferenceScanner(proj.dir)
            stale_refs = scanner.validate_no_stale_references("scr_agent_proof")

            self.assertEqual(stale_refs, [])

    def test_default_argument_asset_reference_is_not_a_parameter_binding(self):
        source = "function probe(chosen = o_target) { return chosen; }"

        self.assertEqual(find_gml_ambiguous_asset_bindings(source, "o_target"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
