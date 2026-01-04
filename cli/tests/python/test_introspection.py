#!/usr/bin/env python3
"""
Comprehensive test suite for introspection helpers.
Tests all asset types, deep mode, error handling, and edge cases.
"""

import json
import os
import sys
import unittest
import tempfile
from pathlib import Path

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.introspection import (
    list_assets_by_type,
    read_asset_yy,
    get_asset_yy_path,
    search_references,
    build_project_index,
    build_asset_graph,
    get_project_stats,
    ASSET_TYPE_MAP,
    GML_REFERENCE_PATTERNS,
)


class TestAssetTypeMap(unittest.TestCase):
    """Test that all asset types are properly mapped."""
    
    def test_all_core_types_mapped(self):
        """Verify all core GameMaker asset types are in the map."""
        required_types = [
            "scripts", "objects", "sprites", "rooms", "sounds",
            "fonts", "shaders", "paths", "timelines", "tilesets",
            "animcurves", "sequences", "notes", "folders"
        ]
        for t in required_types:
            self.assertIn(t, ASSET_TYPE_MAP, f"Missing type mapping for {t}")
    
    def test_extensions_and_datafiles_mapped(self):
        """Verify extensions and datafiles are properly mapped."""
        self.assertIn("extensions", ASSET_TYPE_MAP)
        self.assertIn("datafiles", ASSET_TYPE_MAP)
        self.assertEqual(ASSET_TYPE_MAP["extensions"], "extension")
        self.assertEqual(ASSET_TYPE_MAP["datafiles"], "includedfile")


class TestGMLPatterns(unittest.TestCase):
    """Test GML reference patterns for deep mode."""
    
    def test_instance_create_patterns(self):
        """Test instance creation patterns match correctly."""
        import re
        patterns = GML_REFERENCE_PATTERNS["instance_create"]
        
        test_cases = [
            ("instance_create_layer(x, y, \"Instances\", o_enemy)", "o_enemy"),
            ("instance_create_depth(x, y, 0, o_player)", "o_player"),
            ("instance_create(100, 200, o_bullet)", "o_bullet"),
        ]
        
        for code, expected in test_cases:
            found = False
            for pattern in patterns:
                match = re.search(pattern, code, re.IGNORECASE)
                if match and match.group(1) == expected:
                    found = True
                    break
            self.assertTrue(found, f"Pattern should match '{expected}' in: {code}")
    
    def test_sprite_assignment_patterns(self):
        """Test sprite assignment patterns match correctly."""
        import re
        patterns = GML_REFERENCE_PATTERNS["sprite_assignment"]
        
        test_cases = [
            ("sprite_index = spr_player_walk", "spr_player_walk"),
            ("draw_sprite(spr_icon, 0, x, y)", "spr_icon"),
            ("draw_sprite_ext(spr_bullet, 0, x, y, 1, 1, 0, c_white, 1)", "spr_bullet"),
        ]
        
        for code, expected in test_cases:
            found = False
            for pattern in patterns:
                match = re.search(pattern, code, re.IGNORECASE)
                if match and match.group(1) == expected:
                    found = True
                    break
            self.assertTrue(found, f"Pattern should match '{expected}' in: {code}")


class TestIntrospectionBasics(unittest.TestCase):
    """Test basic introspection functionality."""
    
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.test_dir.name)
        
        # Create a comprehensive mock .yyp file
        self.yyp_data = {
            "$GMProject": "v1",
            "%Name": "TestGame",
            "resources": [
                {"id": {"name": "o_player", "path": "objects/o_player/o_player.yy"}},
                {"id": {"name": "scr_utils", "path": "scripts/scr_utils/scr_utils.yy"}},
                {"id": {"name": "spr_player", "path": "sprites/spr_player/spr_player.yy"}},
                {"id": {"name": "r_main", "path": "rooms/r_main/r_main.yy"}},
                {"id": {"name": "snd_jump", "path": "sounds/snd_jump/snd_jump.yy"}},
                {"id": {"name": "fnt_main", "path": "fonts/fnt_main/fnt_main.yy"}},
                {"id": {"name": "sh_blur", "path": "shaders/sh_blur/sh_blur.yy"}},
                {"id": {"name": "ext_steam", "path": "extensions/ext_steam/ext_steam.yy"}},
            ],
            "Folders": [
                {"name": "Objects", "folderPath": "folders/Objects.yy"},
                {"name": "Scripts", "folderPath": "folders/Scripts.yy"}
            ],
            "IncludedFiles": [
                {"name": "config.json", "filePath": "datafiles/config.json", "CopyToMask": -1},
                {"name": "levels.dat", "filePath": "datafiles/levels.dat", "CopyToMask": -1}
            ],
            "RoomOrderNodes": [
                {"roomId": {"name": "r_main", "path": "rooms/r_main/r_main.yy"}}
            ],
            "AudioGroups": [
                {"name": "audiogroup_default", "targets": -1}
            ],
            "TextureGroups": [
                {"name": "Default", "autocrop": True, "border": 2}
            ],
            "MetaData": {
                "IDEVersion": "2024.14.0.0"
            }
        }
        with open(self.project_root / "TestGame.yyp", "w") as f:
            json.dump(self.yyp_data, f)
        
        # Create mock asset directories and files
        self._create_mock_assets()

    def _create_mock_assets(self):
        """Create mock asset files for testing."""
        # Object with sprite and parent references
        os.makedirs(self.project_root / "objects" / "o_player")
        player_yy = {
            "$GMObject": "",
            "name": "o_player",
            "resourceType": "GMObject",
            "spriteId": {"name": "spr_player", "path": "sprites/spr_player/spr_player.yy"},
            "parentObjectId": {"name": "o_actor", "path": "objects/o_actor/o_actor.yy"},
            "eventList": []
        }
        with open(self.project_root / "objects" / "o_player" / "o_player.yy", "w") as f:
            json.dump(player_yy, f)
        
        # Script with GML code
        os.makedirs(self.project_root / "scripts" / "scr_utils")
        with open(self.project_root / "scripts" / "scr_utils" / "scr_utils.yy", "w") as f:
            json.dump({"name": "scr_utils", "resourceType": "GMScript"}, f)
        with open(self.project_root / "scripts" / "scr_utils" / "scr_utils.gml", "w") as f:
            f.write("""/// @function scr_utils()
function scr_spawn_enemy() {
    instance_create_layer(x, y, "Instances", o_player);
    var snd = audio_play_sound(snd_jump, 1, false);
    sprite_index = spr_player;
}
""")
        
        # Extension
        os.makedirs(self.project_root / "extensions" / "ext_steam")
        with open(self.project_root / "extensions" / "ext_steam" / "ext_steam.yy", "w") as f:
            json.dump({
                "name": "ext_steam",
                "resourceType": "GMExtension",
                "files": [
                    {"functions": [{"name": "steam_init"}]}
                ]
            }, f)
        
        # Datafiles
        os.makedirs(self.project_root / "datafiles")
        with open(self.project_root / "datafiles" / "config.json", "w") as f:
            json.dump({"version": "1.0"}, f)

    def tearDown(self):
        self.test_dir.cleanup()

    # -------------------------------------------------------------------------
    # list_assets_by_type tests
    # -------------------------------------------------------------------------
    
    def test_list_assets_all_types(self):
        """Test listing all asset types."""
        assets = list_assets_by_type(self.project_root)
        
        self.assertIn("object", assets)
        self.assertIn("script", assets)
        self.assertIn("sprite", assets)
        self.assertIn("extension", assets)
        self.assertIn("includedfile", assets)
        
        self.assertEqual(assets["object"][0]["name"], "o_player")
        self.assertEqual(len(assets["includedfile"]), 2)
    
    def test_list_assets_filter_by_type(self):
        """Test filtering by specific asset type."""
        assets = list_assets_by_type(self.project_root, asset_type_filter="object")
        
        self.assertIn("object", assets)
        self.assertNotIn("script", assets)
        self.assertEqual(len(assets["object"]), 1)
    
    def test_list_assets_extension_type(self):
        """Test that extensions are properly listed."""
        assets = list_assets_by_type(self.project_root, asset_type_filter="extension")
        
        self.assertIn("extension", assets)
        self.assertEqual(assets["extension"][0]["name"], "ext_steam")
    
    def test_list_assets_includedfiles(self):
        """Test that included files (datafiles) are properly listed."""
        assets = list_assets_by_type(self.project_root, asset_type_filter="includedfile")
        
        self.assertIn("includedfile", assets)
        names = [a["name"] for a in assets["includedfile"]]
        self.assertIn("config.json", names)
        self.assertIn("levels.dat", names)
    
    def test_list_assets_exclude_includedfiles(self):
        """Test excluding included files from listing."""
        assets = list_assets_by_type(self.project_root, include_included_files=False)
        
        self.assertNotIn("includedfile", assets)

    def test_list_assets_name_contains(self):
        """Test filtering assets by name fragment."""
        # Find o_player
        assets = list_assets_by_type(self.project_root, name_contains="player")
        self.assertIn("object", assets)
        self.assertIn("sprite", assets)
        self.assertEqual(assets["object"][0]["name"], "o_player")
        self.assertEqual(assets["sprite"][0]["name"], "spr_player")
        
        # Should not findscr_utils
        self.assertNotIn("script", assets)

    def test_list_assets_folder_prefix(self):
        """Test filtering assets by folder path."""
        # Filter by objects folder
        assets = list_assets_by_type(self.project_root, folder_prefix="objects")
        self.assertIn("object", assets)
        self.assertNotIn("script", assets)
        self.assertNotIn("sprite", assets)
        
        # Filter by scripts folder
        assets = list_assets_by_type(self.project_root, folder_prefix="scripts")
        self.assertIn("script", assets)
        self.assertNotIn("object", assets)

    def test_list_assets_combined_filters(self):
        """Test combining multiple filters."""
        # Type + Name
        assets = list_assets_by_type(
            self.project_root, 
            asset_type_filter="object", 
            name_contains="player"
        )
        self.assertEqual(len(assets.get("object", [])), 1)
        self.assertNotIn("sprite", assets)
        
        # Type + Folder
        assets = list_assets_by_type(
            self.project_root, 
            asset_type_filter="script", 
            folder_prefix="scripts"
        )
        self.assertEqual(len(assets.get("script", [])), 1)
        self.assertNotIn("object", assets)


    # -------------------------------------------------------------------------
    # read_asset_yy tests
    # -------------------------------------------------------------------------
    
    def test_read_asset_by_name(self):
        """Test reading asset by name."""
        data = read_asset_yy(self.project_root, "o_player")
        
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "o_player")
        self.assertEqual(data["resourceType"], "GMObject")
    
    def test_read_asset_by_path(self):
        """Test reading asset by path."""
        data = read_asset_yy(self.project_root, "objects/o_player/o_player.yy")
        
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "o_player")
    
    def test_read_nonexistent_asset(self):
        """Test reading an asset that doesn't exist."""
        data = read_asset_yy(self.project_root, "nonexistent_asset")
        
        self.assertIsNone(data)

    # -------------------------------------------------------------------------
    # search_references tests
    # -------------------------------------------------------------------------
    
    def test_search_simple_string(self):
        """Test simple string search."""
        results = search_references(self.project_root, "o_player")
        
        self.assertGreater(len(results), 0)
        files = [r["file"] for r in results]
        self.assertTrue(any("scr_utils.gml" in f for f in files))
    
    def test_search_regex(self):
        """Test regex search."""
        results = search_references(self.project_root, r"spr_\w+", is_regex=True)
        
        self.assertGreater(len(results), 0)
    
    def test_search_case_insensitive(self):
        """Test case-insensitive search."""
        results = search_references(self.project_root, "O_PLAYER", case_sensitive=False)
        
        self.assertGreater(len(results), 0)
    
    def test_search_scope_gml(self):
        """Test scoped search to GML files only."""
        results = search_references(self.project_root, "o_player", scope="gml")
        
        for r in results:
            self.assertTrue(r["file"].endswith(".gml"))
    
    def test_search_max_results(self):
        """Test max results limit."""
        results = search_references(self.project_root, "o_player", max_results=1)
        
        self.assertLessEqual(len(results), 1)
    
    def test_search_invalid_regex(self):
        """Test handling of invalid regex."""
        results = search_references(self.project_root, "[invalid(regex", is_regex=True)
        
        # Should return empty or error dict
        self.assertTrue(len(results) == 0 or (len(results) == 1 and "error" in results[0]))

    # -------------------------------------------------------------------------
    # build_project_index tests
    # -------------------------------------------------------------------------
    
    def test_build_project_index_complete(self):
        """Test building a complete project index."""
        index = build_project_index(self.project_root)
        
        self.assertEqual(index["project_name"], "TestGame")
        self.assertIn("assets", index)
        self.assertIn("folders", index)
        self.assertIn("room_order", index)
        self.assertIn("audio_groups", index)
        self.assertIn("texture_groups", index)
        self.assertIn("ide_version", index)
        self.assertEqual(index["ide_version"], "2024.14.0.0")
    
    def test_build_project_index_asset_counts(self):
        """Test asset counts in project index."""
        index = build_project_index(self.project_root)
        
        self.assertIn("asset_counts", index)
        self.assertIn("total_assets", index)
        self.assertGreater(index["total_assets"], 0)

    # -------------------------------------------------------------------------
    # build_asset_graph tests
    # -------------------------------------------------------------------------
    
    def test_build_asset_graph_shallow(self):
        """Test building shallow asset graph (structural refs only)."""
        graph = build_asset_graph(self.project_root, deep=False)
        
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertFalse(graph["deep_scan"])
        
        # Should have sprite relationship from o_player
        sprite_edges = [e for e in graph["edges"] if e["relation"] == "sprite"]
        self.assertGreater(len(sprite_edges), 0)
    
    def test_build_asset_graph_deep(self):
        """Test building deep asset graph (includes code refs)."""
        graph = build_asset_graph(self.project_root, deep=True)
        
        self.assertTrue(graph["deep_scan"])
        
        # Should find code references from GML
        code_refs = [e for e in graph["edges"] if e["relation"] == "code_reference"]
        self.assertGreater(len(code_refs), 0)
    
    def test_build_asset_graph_parent_edge(self):
        """Test that parent object edges are created."""
        graph = build_asset_graph(self.project_root)
        
        parent_edges = [e for e in graph["edges"] if e["relation"] == "parent"]
        self.assertTrue(any(e["from"] == "o_player" and e["to"] == "o_actor" for e in parent_edges))

    # -------------------------------------------------------------------------
    # get_project_stats tests
    # -------------------------------------------------------------------------
    
    def test_get_project_stats(self):
        """Test getting project statistics."""
        stats = get_project_stats(self.project_root)
        
        self.assertIn("total_resources", stats)
        self.assertIn("total_included_files", stats)
        self.assertIn("counts_by_type", stats)
        self.assertEqual(stats["total_included_files"], 2)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""
    
    def test_empty_project(self):
        """Test handling of empty project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            # Create minimal .yyp
            yyp = {"resources": [], "Folders": [], "IncludedFiles": []}
            with open(project_root / "Empty.yyp", "w") as f:
                json.dump(yyp, f)
            
            assets = list_assets_by_type(project_root)
            self.assertEqual(assets, {})
    
    def test_no_yyp_file(self):
        """Test handling of missing .yyp file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            assets = list_assets_by_type(project_root)
            self.assertEqual(assets, {})
    
    def test_malformed_yyp(self):
        """Test handling of malformed .yyp file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            with open(project_root / "Bad.yyp", "w") as f:
                f.write("not valid json {{{")
            
            assets = list_assets_by_type(project_root)
            self.assertEqual(assets, {})
    
    def test_missing_asset_file(self):
        """Test handling of asset in .yyp but missing on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            
            yyp = {
                "resources": [
                    {"id": {"name": "missing_asset", "path": "objects/missing/missing.yy"}}
                ]
            }
            with open(project_root / "Test.yyp", "w") as f:
                json.dump(yyp, f)
            
            # list_assets should still work (just lists from .yyp)
            assets = list_assets_by_type(project_root)
            self.assertEqual(len(assets.get("object", [])), 1)
            
            # read_asset_yy should return None for missing file
            data = read_asset_yy(project_root, "missing_asset")
            self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main()
