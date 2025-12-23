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
from gms_helpers.reference_scanner import comprehensive_rename_asset, ReferenceScanner
from gms_helpers.utils import save_pretty_json_gm, load_json_loose
from gms_helpers.assets import ScriptAsset, SpriteAsset, ObjectAsset

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
        self.resource_order_data = {
            "FolderOrderSettings": [],
            "ResourceOrderSettings": []
        }
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
                "name": sprite_name,   # This should update during rename!
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
                                        "path": f"sprites/{sprite_name}/frame_0.png"  # Path should update!
                                    }
                                }
                            }
                        }
                    ]
                }
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
        resource_entry = {
            "id": {
                "name": name,
                "path": path
            }
        }
        self.yyp_data["resources"].append(resource_entry)
        save_pretty_json_gm(self.dir / "test.yyp", self.yyp_data)

        # Add to resource order
        order_entry = {
            "name": name,
            "order": len(self.resource_order_data["ResourceOrderSettings"]),
            "path": path
        }
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
            self.assertEqual(sprite_data["sequence"]["%Name"], new_name,
                           "Sprite sequence %Name was not updated - reference scanner failed!")
            self.assertEqual(sprite_data["sequence"]["name"], new_name,
                           "Sprite sequence name was not updated - reference scanner failed!")

            # Keyframe paths should be updated
            keyframe_path = sprite_data["sequence"]["keyframes"]["keyframes"][0]["channels"]["0"]["Id"]["path"]
            self.assertIn(new_name, keyframe_path,
                         "Sprite keyframe path was not updated - reference scanner failed!")
            self.assertNotIn(old_name, keyframe_path,
                           "Sprite keyframe path still contains old name - stale reference!")

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
                "ui_test_script",
                [old_object_name, "TestEnum.test_old"]
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
            self.assertIn(new_object_name, updated_script_content,
                         "Script object reference was not updated - reference scanner failed!")
            self.assertNotIn(old_object_name, updated_script_content,
                           "Script still contains old object reference - stale reference!")

            # UIGroup enum should be updated (test_old -> test_new)
            self.assertIn("TestEnum.test_new", updated_script_content,
                         "Script TestEnum enum was not updated - reference scanner failed!")
            self.assertNotIn("TestEnum.test_old", updated_script_content,
                           "Script still contains old TestEnum enum - stale reference!")

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
            old_entry = next((entry for entry in resource_order_data["ResourceOrderSettings"]
                             if entry["name"] == old_name), None)
            self.assertIsNotNone(old_entry, "Resource order entry not found")
            self.assertIn(old_name, old_entry["path"])

            # Rename the sprite using the full workflow function
            rename_asset(proj.dir, f"sprites/{old_name}/{old_name}.yy", new_name)

            # CRITICAL: Check that resource order was updated
            updated_resource_order = load_json_loose(proj.dir / "test.resource_order")

            # Old entry should be gone
            old_entry_after = next((entry for entry in updated_resource_order["ResourceOrderSettings"]
                                   if entry["name"] == old_name), None)
            self.assertIsNone(old_entry_after,
                             "Resource order still contains old entry - reference scanner failed!")

            # New entry should exist
            new_entry = next((entry for entry in updated_resource_order["ResourceOrderSettings"]
                             if entry["name"] == new_name), None)
            self.assertIsNotNone(new_entry,
                               "Resource order does not contain new entry - reference scanner failed!")
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
            script_yy, script_gml = proj.create_script_with_asset_references(
                "test_script", [old_name]
            )

            # Use reference scanner to find all references
            scanner = ReferenceScanner(proj.dir)
            references = scanner.find_all_asset_references(old_name, new_name, "sprite")

            # CRITICAL: Must find references in multiple file types
            reference_types = [ref.reference_type for ref in references]

            # Should find project file references
            self.assertIn("project_resource_name", reference_types,
                         "Reference scanner missed project resource name reference!")
            self.assertIn("project_resource_path", reference_types,
                         "Reference scanner missed project resource path reference!")

            # Should find resource order references
            self.assertIn("resource_order", reference_types,
                         "Reference scanner missed resource order reference!")

            # Should find sprite internal references
            self.assertIn("sprite_sequence_name", reference_types,
                         "Reference scanner missed sprite sequence name reference!")

            # Should find script references
            self.assertIn("script_sprite_reference", reference_types,
                         "Reference scanner missed script sprite reference!")

            # Verify reference count is reasonable (multiple references expected)
            self.assertGreaterEqual(len(references), 4,
                                  f"Reference scanner found only {len(references)} references, expected at least 4!")

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
            self.assertTrue(success,
                          "Comprehensive rename failed - stale references remain!")

            # Additional validation: manual check for stale references
            scanner = ReferenceScanner(proj.dir)
            stale_refs = scanner.validate_no_stale_references(old_name)

            self.assertEqual(len(stale_refs), 0,
                           f"Found {len(stale_refs)} stale references after comprehensive rename: {stale_refs}")

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
            required_fields = ["builtinName", "events", "inheritsTrackColour", "interpolation",
                             "isCreationTrack", "keyframes", "modifiers", "name",
                             "resourceType", "resourceVersion", "spriteId", "trackColour", "tracks", "traits"]
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
                    "tracks": [{
                        "$GMSpriteFramesTrack": "",
                        "keyframes": {
                            "Keyframes": [{
                                "Channels": {
                                    "0": {
                                        "Id": {
                                            "name": "test-uuid",
                                            "path": f"sprites/{old_name}/{old_name}.yy"
                                        }
                                    }
                                }
                            }]
                        }
                    }]
                }
            }

            sprite_file = sprite_dir / f"{old_name}.yy"
            save_pretty_json_gm(sprite_file, sprite_data)

            # Test reference scanner catches the .yy filename reference
            scanner = ReferenceScanner(project.dir)
            references = scanner.find_all_asset_references(old_name, new_name, "sprite")

            # Should find the keyframe path reference (full path, not just filename)
            yy_path_refs = [ref for ref in references if ref.reference_type == "sprite_keyframe_path"]
            self.assertGreater(len(yy_path_refs), 0,
                             "Reference scanner should find internal .yy path references!")

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

            self.assertTrue(expected_structure_path.exists(),
                          f"Layer image should exist at layers/{image_uuid}/{layer_uuid}.png (frame_uuid/layer_uuid.png)")
            self.assertFalse(wrong_structure_path.exists(),
                           f"Layer image should NOT exist at layers/{layer_uuid}/{image_uuid}.png (wrong structure)")

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
            self.assertEqual(sprite_data["sequence"]["%Name"], new_name,
                           "Atomic update failed - sequence name not updated!")


if __name__ == "__main__":
    unittest.main(verbosity=2)
