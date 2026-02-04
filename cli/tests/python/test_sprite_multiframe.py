#!/usr/bin/env python3
"""
Test suite for multi-frame sprite support.
Tests sprite creation with frame_count, frame manipulation, and sprite import.
"""

import unittest
import tempfile
import shutil
import json
from pathlib import Path

# Define PROJECT_ROOT before using it
PROJECT_ROOT = Path(__file__).resolve().parents[3]

import sys
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.assets import SpriteAsset
from gms_helpers.utils import load_json_loose, generate_uuid


class TestSpriteMultiframeBase(unittest.TestCase):
    """Base test class with common setup."""
    
    def setUp(self):
        """Set up test environment with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create basic project structure
        for folder in ['sprites', 'folders']:
            (self.project_root / folder).mkdir(exist_ok=True)
        
        # Create a basic .yyp file
        self._create_basic_yyp_file()
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_basic_yyp_file(self):
        """Create a basic .yyp file."""
        yyp_path = self.project_root / "TestProject.yyp"
        yyp_data = {
            "$GMProject": "",
            "%Name": "TestProject",
            "name": "TestProject",
            "resources": [],
            "Folders": [],
            "resourceType": "GMProject",
            "resourceVersion": "2.0"
        }
        
        with open(yyp_path, 'w') as f:
            json.dump(yyp_data, f, indent=2)
        
        return yyp_path


class TestSpriteCreationWithFrameCount(TestSpriteMultiframeBase):
    """Test sprite creation with frame_count parameter."""
    
    def test_create_single_frame_sprite_default(self):
        """Test that default frame_count is 1 (backwards compatible)."""
        asset = SpriteAsset()
        relative_path = asset.create_files(self.project_root, "spr_test", "")
        
        yy_path = self.project_root / "sprites" / "spr_test" / "spr_test.yy"
        self.assertTrue(yy_path.exists())
        
        yy_data = load_json_loose(yy_path)
        self.assertEqual(len(yy_data["frames"]), 1)
        self.assertEqual(yy_data["sequence"]["length"], 1.0)
        
        # Check keyframes
        keyframes = yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
        self.assertEqual(len(keyframes), 1)
        self.assertEqual(keyframes[0]["Key"], 0.0)
    
    def test_create_sprite_with_5_frames(self):
        """Test creating a sprite with 5 frames."""
        asset = SpriteAsset()
        relative_path = asset.create_files(self.project_root, "spr_anim", "", frame_count=5)
        
        yy_path = self.project_root / "sprites" / "spr_anim" / "spr_anim.yy"
        self.assertTrue(yy_path.exists())
        
        yy_data = load_json_loose(yy_path)
        
        # Check frames array
        self.assertEqual(len(yy_data["frames"]), 5)
        
        # Check sequence length
        self.assertEqual(yy_data["sequence"]["length"], 5.0)
        
        # Check keyframes
        keyframes = yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
        self.assertEqual(len(keyframes), 5)
        
        # Verify keyframe Keys are 0.0, 1.0, 2.0, 3.0, 4.0
        for i, kf in enumerate(keyframes):
            self.assertEqual(kf["Key"], float(i))
            self.assertEqual(kf["Length"], 1.0)
        
        # Verify each frame UUID is unique
        frame_uuids = [f["name"] for f in yy_data["frames"]]
        self.assertEqual(len(frame_uuids), len(set(frame_uuids)))
        
        # Verify keyframes reference correct frame UUIDs
        for i, kf in enumerate(keyframes):
            kf_frame_uuid = kf["Channels"]["0"]["Id"]["name"]
            self.assertEqual(kf_frame_uuid, frame_uuids[i])
    
    def test_create_sprite_creates_correct_png_files(self):
        """Test that correct number of PNG files are created."""
        asset = SpriteAsset()
        asset.create_files(self.project_root, "spr_multi", "", frame_count=3)
        
        sprite_folder = self.project_root / "sprites" / "spr_multi"
        yy_path = sprite_folder / "spr_multi.yy"
        yy_data = load_json_loose(yy_path)
        
        # Check each frame has its PNG
        for frame in yy_data["frames"]:
            frame_uuid = frame["name"]
            main_png = sprite_folder / f"{frame_uuid}.png"
            self.assertTrue(main_png.exists(), f"Missing main PNG: {main_png}")
        
        # Count PNG files (should be 3)
        png_files = list(sprite_folder.glob("*.png"))
        self.assertEqual(len(png_files), 3)
    
    def test_create_sprite_creates_correct_layer_structure(self):
        """Test that layer directories are created correctly."""
        asset = SpriteAsset()
        asset.create_files(self.project_root, "spr_layers", "", frame_count=4)
        
        sprite_folder = self.project_root / "sprites" / "spr_layers"
        yy_path = sprite_folder / "spr_layers.yy"
        yy_data = load_json_loose(yy_path)
        
        layer_uuid = yy_data["layers"][0]["name"]
        
        # Check each frame has its layer directory with the layer PNG
        for frame in yy_data["frames"]:
            frame_uuid = frame["name"]
            layer_dir = sprite_folder / "layers" / frame_uuid
            self.assertTrue(layer_dir.exists(), f"Missing layer dir: {layer_dir}")
            
            layer_png = layer_dir / f"{layer_uuid}.png"
            self.assertTrue(layer_png.exists(), f"Missing layer PNG: {layer_png}")
    
    def test_create_sprite_with_zero_frames_defaults_to_one(self):
        """Test that frame_count=0 defaults to 1."""
        asset = SpriteAsset()
        asset.create_files(self.project_root, "spr_zero", "", frame_count=0)
        
        yy_path = self.project_root / "sprites" / "spr_zero" / "spr_zero.yy"
        yy_data = load_json_loose(yy_path)
        
        self.assertEqual(len(yy_data["frames"]), 1)
    
    def test_create_sprite_with_negative_frames_defaults_to_one(self):
        """Test that negative frame_count defaults to 1."""
        asset = SpriteAsset()
        asset.create_files(self.project_root, "spr_neg", "", frame_count=-5)
        
        yy_path = self.project_root / "sprites" / "spr_neg" / "spr_neg.yy"
        yy_data = load_json_loose(yy_path)
        
        self.assertEqual(len(yy_data["frames"]), 1)
    
    def test_create_sprite_with_custom_dimensions(self):
        """Test sprite creation with custom width/height."""
        asset = SpriteAsset()
        asset.create_files(self.project_root, "spr_sized", "", frame_count=2, width=64, height=32)
        
        yy_path = self.project_root / "sprites" / "spr_sized" / "spr_sized.yy"
        yy_data = load_json_loose(yy_path)
        
        self.assertEqual(yy_data["width"], 64)
        self.assertEqual(yy_data["height"], 32)
        self.assertEqual(yy_data["bbox_right"], 63)
        self.assertEqual(yy_data["bbox_bottom"], 31)


class TestSpriteFrameManipulation(TestSpriteMultiframeBase):
    """Test sprite frame add/remove/duplicate operations."""
    
    def _create_test_sprite(self, name: str, frame_count: int = 1):
        """Helper to create a test sprite."""
        asset = SpriteAsset()
        asset.create_files(self.project_root, name, "", frame_count=frame_count)
        return f"sprites/{name}/{name}.yy"
    
    def test_add_frame_at_end(self):
        """Test adding a frame at the end of a sprite."""
        from gms_helpers.sprite_frames import add_frame, get_frame_count
        
        sprite_path = self._create_test_sprite("spr_add_end", frame_count=2)
        
        result = add_frame(self.project_root, sprite_path, position=-1)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["position"], 2)
        self.assertEqual(result["new_frame_count"], 3)
        self.assertEqual(get_frame_count(self.project_root, sprite_path), 3)
    
    def test_add_frame_at_start(self):
        """Test adding a frame at position 0."""
        from gms_helpers.sprite_frames import add_frame, get_frame_count
        
        sprite_path = self._create_test_sprite("spr_add_start", frame_count=2)
        
        result = add_frame(self.project_root, sprite_path, position=0)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["position"], 0)
        self.assertEqual(result["new_frame_count"], 3)
        
        # Verify keyframes were shifted
        yy_path = self.project_root / sprite_path
        yy_data = load_json_loose(yy_path)
        keyframes = yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
        
        # Keys should be 0.0, 1.0, 2.0
        keys = sorted([kf["Key"] for kf in keyframes])
        self.assertEqual(keys, [0.0, 1.0, 2.0])
    
    def test_add_frame_in_middle(self):
        """Test adding a frame in the middle."""
        from gms_helpers.sprite_frames import add_frame
        
        sprite_path = self._create_test_sprite("spr_add_mid", frame_count=3)
        
        result = add_frame(self.project_root, sprite_path, position=1)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["position"], 1)
        self.assertEqual(result["new_frame_count"], 4)
    
    def test_remove_frame(self):
        """Test removing a frame from a sprite."""
        from gms_helpers.sprite_frames import remove_frame, get_frame_count
        
        sprite_path = self._create_test_sprite("spr_remove", frame_count=3)
        
        result = remove_frame(self.project_root, sprite_path, position=1)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["removed_position"], 1)
        self.assertEqual(result["new_frame_count"], 2)
        self.assertEqual(get_frame_count(self.project_root, sprite_path), 2)
        
        # Verify keyframes were shifted
        yy_path = self.project_root / sprite_path
        yy_data = load_json_loose(yy_path)
        keyframes = yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
        
        keys = sorted([kf["Key"] for kf in keyframes])
        self.assertEqual(keys, [0.0, 1.0])
    
    def test_remove_last_frame_error(self):
        """Test that removing the only frame raises an error."""
        from gms_helpers.sprite_frames import remove_frame
        from gms_helpers.exceptions import ValidationError
        
        sprite_path = self._create_test_sprite("spr_single", frame_count=1)
        
        with self.assertRaises(ValidationError):
            remove_frame(self.project_root, sprite_path, position=0)
    
    def test_remove_invalid_position_error(self):
        """Test that removing an invalid position raises an error."""
        from gms_helpers.sprite_frames import remove_frame
        from gms_helpers.exceptions import ValidationError
        
        sprite_path = self._create_test_sprite("spr_invalid", frame_count=3)
        
        with self.assertRaises(ValidationError):
            remove_frame(self.project_root, sprite_path, position=5)
    
    def test_duplicate_frame(self):
        """Test duplicating a frame."""
        from gms_helpers.sprite_frames import duplicate_frame, get_frame_count
        
        sprite_path = self._create_test_sprite("spr_dup", frame_count=2)
        
        result = duplicate_frame(self.project_root, sprite_path, source_position=0)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["position"], 1)  # After source
        self.assertEqual(result["new_frame_count"], 3)
    
    def test_duplicate_frame_to_specific_position(self):
        """Test duplicating a frame to a specific position."""
        from gms_helpers.sprite_frames import duplicate_frame
        
        sprite_path = self._create_test_sprite("spr_dup_pos", frame_count=3)
        
        result = duplicate_frame(self.project_root, sprite_path, source_position=2, target_position=0)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["position"], 0)
        self.assertEqual(result["new_frame_count"], 4)
    
    def test_add_frame_creates_png_files(self):
        """Test that adding a frame creates the necessary PNG files."""
        from gms_helpers.sprite_frames import add_frame
        
        sprite_path = self._create_test_sprite("spr_png", frame_count=1)
        result = add_frame(self.project_root, sprite_path)
        
        new_uuid = result["frame_uuid"]
        sprite_folder = self.project_root / "sprites" / "spr_png"
        
        # Check main PNG exists
        main_png = sprite_folder / f"{new_uuid}.png"
        self.assertTrue(main_png.exists())
        
        # Check layer PNG exists
        layer_dir = sprite_folder / "layers" / new_uuid
        self.assertTrue(layer_dir.exists())
        self.assertTrue(len(list(layer_dir.glob("*.png"))) == 1)
    
    def test_remove_frame_deletes_png_files(self):
        """Test that removing a frame deletes the PNG files."""
        from gms_helpers.sprite_frames import remove_frame
        
        sprite_path = self._create_test_sprite("spr_del_png", frame_count=2)
        
        # Get the UUID of the frame we're about to remove
        yy_path = self.project_root / sprite_path
        yy_data = load_json_loose(yy_path)
        frame_uuid = yy_data["frames"][1]["name"]
        
        sprite_folder = self.project_root / "sprites" / "spr_del_png"
        main_png = sprite_folder / f"{frame_uuid}.png"
        layer_dir = sprite_folder / "layers" / frame_uuid
        
        # Verify files exist before removal
        self.assertTrue(main_png.exists())
        self.assertTrue(layer_dir.exists())
        
        # Remove the frame
        remove_frame(self.project_root, sprite_path, position=1)
        
        # Verify files are deleted
        self.assertFalse(main_png.exists())
        self.assertFalse(layer_dir.exists())


class TestSwapSpriteFrame(TestSpriteMultiframeBase):
    """Test swapping specific frames."""
    
    def _create_test_sprite(self, name: str, frame_count: int = 1):
        """Helper to create a test sprite."""
        asset = SpriteAsset()
        asset.create_files(self.project_root, name, "", frame_count=frame_count)
        return f"sprites/{name}/{name}.yy"
    
    def _create_test_png(self, name: str = "test.png"):
        """Create a simple test PNG file."""
        from gms_helpers.utils import create_dummy_png
        
        png_path = self.project_root / name
        create_dummy_png(png_path, width=32, height=32)
        return png_path
    
    def test_swap_first_frame(self):
        """Test swapping frame 0 (default behavior)."""
        from gms_helpers.workflow import swap_sprite_png
        
        sprite_path = self._create_test_sprite("spr_swap0", frame_count=3)
        test_png = self._create_test_png()
        
        result = swap_sprite_png(
            self.project_root,
            sprite_path,
            test_png,
            frame_index=0
        )
        
        self.assertTrue(result.success)
    
    def test_swap_middle_frame(self):
        """Test swapping a middle frame."""
        from gms_helpers.workflow import swap_sprite_png
        
        sprite_path = self._create_test_sprite("spr_swap_mid", frame_count=5)
        test_png = self._create_test_png()
        
        result = swap_sprite_png(
            self.project_root,
            sprite_path,
            test_png,
            frame_index=2
        )
        
        self.assertTrue(result.success)
    
    def test_swap_last_frame(self):
        """Test swapping the last frame."""
        from gms_helpers.workflow import swap_sprite_png
        
        sprite_path = self._create_test_sprite("spr_swap_last", frame_count=4)
        test_png = self._create_test_png()
        
        result = swap_sprite_png(
            self.project_root,
            sprite_path,
            test_png,
            frame_index=3
        )
        
        self.assertTrue(result.success)
    
    def test_swap_invalid_frame_index(self):
        """Test that swapping an invalid frame index raises an error."""
        from gms_helpers.workflow import swap_sprite_png
        
        sprite_path = self._create_test_sprite("spr_swap_invalid", frame_count=3)
        test_png = self._create_test_png()
        
        with self.assertRaises(ValueError) as ctx:
            swap_sprite_png(
                self.project_root,
                sprite_path,
                test_png,
                frame_index=5
            )
        
        self.assertIn("Invalid frame_index", str(ctx.exception))
    
    def test_swap_negative_frame_index(self):
        """Test that swapping a negative frame index raises an error."""
        from gms_helpers.workflow import swap_sprite_png
        
        sprite_path = self._create_test_sprite("spr_swap_neg", frame_count=3)
        test_png = self._create_test_png()
        
        with self.assertRaises(ValueError):
            swap_sprite_png(
                self.project_root,
                sprite_path,
                test_png,
                frame_index=-1
            )


class TestSpriteImport(TestSpriteMultiframeBase):
    """Test sprite strip import functionality."""
    
    def _create_test_strip(self, name: str, frame_count: int, frame_width: int, frame_height: int, layout: str = "horizontal"):
        """Create a test sprite strip image."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        
        if layout == "horizontal":
            width = frame_width * frame_count
            height = frame_height
        elif layout == "vertical":
            width = frame_width
            height = frame_height * frame_count
        else:
            raise ValueError(f"Unsupported layout: {layout}")
        
        # Create a simple colored strip
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        
        for i in range(frame_count):
            # Create unique colored frames
            color = ((i * 50) % 256, (i * 30) % 256, (i * 70) % 256, 255)
            if layout == "horizontal":
                box = (i * frame_width, 0, (i + 1) * frame_width, frame_height)
            else:
                box = (0, i * frame_height, frame_width, (i + 1) * frame_height)
            
            frame_img = Image.new("RGBA", (frame_width, frame_height), color)
            img.paste(frame_img, box[:2])
        
        strip_path = self.project_root / name
        img.save(strip_path, "PNG")
        return strip_path
    
    def test_import_horizontal_strip(self):
        """Test importing a horizontal sprite strip."""
        try:
            from gms_helpers.sprite_import import import_strip_to_sprite
        except ImportError:
            self.skipTest("Pillow not installed")
        
        strip_path = self._create_test_strip("strip_h.png", 4, 32, 32, "horizontal")
        
        result = import_strip_to_sprite(
            self.project_root,
            "spr_imported_h",
            strip_path,
            layout="horizontal"
        )
        
        self.assertTrue(result["success"])
        self.assertEqual(result["frame_count"], 4)
        self.assertEqual(result["frame_size"], (32, 32))
        
        # Verify sprite was created
        yy_path = self.project_root / "sprites" / "spr_imported_h" / "spr_imported_h.yy"
        self.assertTrue(yy_path.exists())
        
        yy_data = load_json_loose(yy_path)
        self.assertEqual(len(yy_data["frames"]), 4)
    
    def test_import_vertical_strip(self):
        """Test importing a vertical sprite strip."""
        try:
            from gms_helpers.sprite_import import import_strip_to_sprite
        except ImportError:
            self.skipTest("Pillow not installed")
        
        strip_path = self._create_test_strip("strip_v.png", 6, 32, 32, "vertical")
        
        result = import_strip_to_sprite(
            self.project_root,
            "spr_imported_v",
            strip_path,
            layout="vertical"
        )
        
        self.assertTrue(result["success"])
        self.assertEqual(result["frame_count"], 6)
    
    def test_import_with_explicit_dimensions(self):
        """Test importing with explicit frame dimensions."""
        try:
            from gms_helpers.sprite_import import import_strip_to_sprite
        except ImportError:
            self.skipTest("Pillow not installed")
        
        strip_path = self._create_test_strip("strip_explicit.png", 3, 64, 48, "horizontal")
        
        result = import_strip_to_sprite(
            self.project_root,
            "spr_explicit",
            strip_path,
            frame_width=64,
            frame_height=48,
            layout="horizontal"
        )
        
        self.assertTrue(result["success"])
        self.assertEqual(result["frame_count"], 3)
        self.assertEqual(result["frame_size"], (64, 48))
    
    def test_import_nonexistent_file_error(self):
        """Test that importing a nonexistent file raises an error."""
        try:
            from gms_helpers.sprite_import import import_strip_to_sprite
        except ImportError:
            self.skipTest("Pillow not installed")
        
        with self.assertRaises(FileNotFoundError):
            import_strip_to_sprite(
                self.project_root,
                "spr_nonexistent",
                Path("/nonexistent/file.png")
            )
    
    def test_detect_strip_layout(self):
        """Test auto-detection of strip layout."""
        try:
            from gms_helpers.sprite_import import detect_strip_layout
        except ImportError:
            self.skipTest("Pillow not installed")
        
        # Create a horizontal strip (wider than tall)
        strip_path = self._create_test_strip("strip_detect.png", 4, 32, 32, "horizontal")
        
        frame_count, frame_width, frame_height = detect_strip_layout(strip_path)
        
        self.assertEqual(frame_count, 4)
        self.assertEqual(frame_width, 32)
        self.assertEqual(frame_height, 32)


class TestSpriteMultiframeIntegration(TestSpriteMultiframeBase):
    """Integration tests for multi-frame sprite operations."""
    
    def test_create_modify_verify(self):
        """Test creating a sprite, adding frames, and verifying structure."""
        from gms_helpers.sprite_frames import add_frame, remove_frame, get_frame_count
        
        # Create initial sprite
        asset = SpriteAsset()
        asset.create_files(self.project_root, "spr_integration", "", frame_count=2)
        sprite_path = "sprites/spr_integration/spr_integration.yy"
        
        # Add 3 more frames
        add_frame(self.project_root, sprite_path)
        add_frame(self.project_root, sprite_path)
        add_frame(self.project_root, sprite_path)
        
        self.assertEqual(get_frame_count(self.project_root, sprite_path), 5)
        
        # Remove 2 frames
        remove_frame(self.project_root, sprite_path, position=2)
        remove_frame(self.project_root, sprite_path, position=0)
        
        self.assertEqual(get_frame_count(self.project_root, sprite_path), 3)
        
        # Verify .yy structure integrity
        yy_path = self.project_root / sprite_path
        yy_data = load_json_loose(yy_path)
        
        self.assertEqual(len(yy_data["frames"]), 3)
        self.assertEqual(yy_data["sequence"]["length"], 3.0)
        
        keyframes = yy_data["sequence"]["tracks"][0]["keyframes"]["Keyframes"]
        self.assertEqual(len(keyframes), 3)
        
        # Verify keyframe keys are contiguous
        keys = sorted([kf["Key"] for kf in keyframes])
        self.assertEqual(keys, [0.0, 1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
