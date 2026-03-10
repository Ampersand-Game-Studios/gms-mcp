#!/usr/bin/env python3
"""Coverage-oriented tests for MCP wrapper modules."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_mcp.server.tools import asset_creation, maintenance, rooms, runner, texture_groups, workflow


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class MCPToolTestCase(unittest.TestCase):
    module = None

    def setUp(self):
        self.mcp = FakeMCP()
        self.module.register(self.mcp, object)

    def call_tool(self, tool_name: str, **kwargs):
        return asyncio.run(self.mcp.tools[tool_name](**kwargs))


class TestAssetCreationWrappers(MCPToolTestCase):
    module = asset_creation

    def test_create_tools_forward_expected_cli_and_asset_types(self):
        with patch(
            "gms_mcp.server.tools.asset_creation._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as mock_fallback:
            cases = [
                ("gm_create_script", {"name": "scr_test", "parent_path": "folders/Scripts.yy", "is_constructor": True, "project_root": "/tmp/project"}, "script"),
                ("gm_create_object", {"name": "o_player", "sprite_id": "spr_player", "parent_object": "o_parent", "project_root": "/tmp/project"}, "object"),
                ("gm_create_sprite", {"name": "spr_player", "frame_count": 4, "project_root": "/tmp/project"}, "sprite"),
                ("gm_create_room", {"name": "r_main", "width": 800, "height": 600, "project_root": "/tmp/project"}, "room"),
                ("gm_create_folder", {"name": "Sprites", "path": "folders/Sprites.yy", "project_root": "/tmp/project"}, "folder"),
                ("gm_create_font", {"name": "fnt_ui", "font_name": "Verdana", "size": 16, "bold": True, "uses_sdf": False, "project_root": "/tmp/project"}, "font"),
                ("gm_create_shader", {"name": "shd_test", "shader_type": 2, "project_root": "/tmp/project"}, "shader"),
                ("gm_create_animcurve", {"name": "ac_curve", "curve_type": "bezier", "channel_name": "value", "project_root": "/tmp/project"}, "animcurve"),
                ("gm_create_sound", {"name": "snd_boom", "volume": 0.8, "pitch": 1.2, "bitrate": 192, "project_root": "/tmp/project"}, "sound"),
                ("gm_create_path", {"name": "pth_main", "closed": True, "precision": 8, "path_type": "curved", "project_root": "/tmp/project"}, "path"),
                ("gm_create_tileset", {"name": "ts_ground", "sprite_id": "spr_tiles", "tile_width": 16, "tile_height": 16, "project_root": "/tmp/project"}, "tileset"),
                ("gm_create_timeline", {"name": "tl_intro", "parent_path": "folders/Timelines.yy", "project_root": "/tmp/project"}, "timeline"),
                ("gm_create_sequence", {"name": "seq_intro", "length": 120.0, "playback_speed": 60.0, "project_root": "/tmp/project"}, "sequence"),
                ("gm_create_note", {"name": "note_readme", "content": "hello", "project_root": "/tmp/project"}, "note"),
            ]

            for tool_name, kwargs, asset_type in cases:
                result = self.call_tool(tool_name, **kwargs)
                self.assertTrue(result["ok"])
                call_kwargs = mock_fallback.await_args_list[-1].kwargs
                self.assertEqual(call_kwargs["direct_args"].asset_type, asset_type)
                self.assertEqual(call_kwargs["project_root"], "/tmp/project")

    def test_asset_delete_supports_dry_run_and_policy_block(self):
        with patch(
            "gms_mcp.server.tools.asset_creation._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as mock_fallback:
            result = self.call_tool(
                "gm_asset_delete",
                asset_type="script",
                name="scr_test",
                dry_run=True,
                project_root="/tmp/project",
            )
        self.assertTrue(result["ok"])
        fallback_kwargs = mock_fallback.await_args.kwargs
        self.assertIn("--dry-run", fallback_kwargs["cli_args"])

        with patch("gms_mcp.server.tools.asset_creation._requires_dry_run_for_tool", return_value=True):
            blocked = self.call_tool(
                "gm_asset_delete",
                asset_type="script",
                name="scr_test",
                dry_run=False,
                project_root="/tmp/project",
            )
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["blocked_by_policy"])


class TestMaintenanceWrappers(MCPToolTestCase):
    module = maintenance

    def test_maintenance_wrappers_forward_cli_args(self):
        with patch(
            "gms_mcp.server.tools.maintenance._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as mock_fallback:
            cases = [
                ("gm_maintenance_auto", {"fix": False, "verbose": False, "project_root": "/tmp/project"}, ["maintenance", "auto", "--no-verbose"]),
                ("gm_maintenance_lint", {"fix": False, "project_root": "/tmp/project"}, ["maintenance", "lint"]),
                ("gm_maintenance_validate_json", {"project_root": "/tmp/project"}, ["maintenance", "validate-json"]),
                ("gm_maintenance_list_orphans", {"project_root": "/tmp/project"}, ["maintenance", "list-orphans"]),
                ("gm_maintenance_prune_missing", {"dry_run": True, "project_root": "/tmp/project"}, ["maintenance", "prune-missing", "--dry-run"]),
                ("gm_maintenance_validate_paths", {"strict_disk_check": True, "include_parent_folders": True, "project_root": "/tmp/project"}, ["maintenance", "validate-paths", "--strict-disk-check", "--include-parent-folders"]),
                ("gm_maintenance_dedupe_resources", {"auto": True, "dry_run": True, "project_root": "/tmp/project"}, ["maintenance", "dedupe-resources", "--auto", "--dry-run"]),
                ("gm_maintenance_sync_events", {"fix": False, "object": "o_player", "project_root": "/tmp/project"}, ["maintenance", "sync-events", "--object", "o_player"]),
                ("gm_maintenance_clean_old_files", {"delete": False, "project_root": "/tmp/project"}, ["maintenance", "clean-old-files"]),
                ("gm_maintenance_clean_orphans", {"delete": False, "skip_types": ["font", "sound"], "project_root": "/tmp/project"}, ["maintenance", "clean-orphans", "--skip-types", "font", "sound"]),
            ]

            for tool_name, kwargs, expected_cli in cases:
                result = self.call_tool(tool_name, **kwargs)
                self.assertTrue(result["ok"])
                self.assertEqual(mock_fallback.await_args_list[-1].kwargs["cli_args"], expected_cli)

        with patch("gms_mcp.server.tools.maintenance._requires_dry_run_for_tool", return_value=True):
            blocked_cases = [
                ("gm_maintenance_auto", {"fix": True, "project_root": "/tmp/project"}),
                ("gm_maintenance_lint", {"fix": True, "project_root": "/tmp/project"}),
                ("gm_maintenance_prune_missing", {"dry_run": False, "project_root": "/tmp/project"}),
                ("gm_maintenance_dedupe_resources", {"auto": False, "dry_run": False, "project_root": "/tmp/project"}),
                ("gm_maintenance_sync_events", {"fix": True, "object": "", "project_root": "/tmp/project"}),
                ("gm_maintenance_clean_old_files", {"delete": True, "project_root": "/tmp/project"}),
                ("gm_maintenance_clean_orphans", {"delete": True, "project_root": "/tmp/project"}),
                ("gm_maintenance_fix_issues", {"verbose": True, "project_root": "/tmp/project"}),
            ]
            for tool_name, kwargs in blocked_cases:
                result = self.call_tool(tool_name, **kwargs)
                self.assertFalse(result["ok"])
                self.assertTrue(result["blocked_by_policy"])


class TestRoomWrappers(MCPToolTestCase):
    module = rooms

    def test_room_wrappers_forward_expected_args(self):
        with patch(
            "gms_mcp.server.tools.rooms._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as mock_fallback:
            cases = [
                ("gm_room_ops_duplicate", {"source_room": "r_old", "new_name": "r_new", "project_root": "/tmp/project"}, ["room", "ops", "duplicate", "r_old", "r_new"]),
                ("gm_room_ops_rename", {"room_name": "r_old", "new_name": "r_new", "project_root": "/tmp/project"}, ["room", "ops", "rename", "r_old", "r_new"]),
                ("gm_room_ops_delete", {"room_name": "r_old", "dry_run": True, "project_root": "/tmp/project"}, ["room", "ops", "delete", "r_old", "--dry-run"]),
                ("gm_room_ops_list", {"verbose": True, "project_root": "/tmp/project"}, ["room", "ops", "list", "--verbose"]),
                ("gm_room_layer_add", {"room_name": "r_main", "layer_type": "instance", "layer_name": "Actors", "depth": 100, "project_root": "/tmp/project"}, ["room", "layer", "add", "r_main", "instance", "Actors", "--depth", "100"]),
                ("gm_room_layer_remove", {"room_name": "r_main", "layer_name": "Actors", "project_root": "/tmp/project"}, ["room", "layer", "remove", "r_main", "Actors"]),
                ("gm_room_layer_list", {"room_name": "r_main", "project_root": "/tmp/project"}, ["room", "layer", "list", "r_main"]),
                ("gm_room_instance_add", {"room_name": "r_main", "object_name": "o_player", "x": 10, "y": 20, "layer": "Actors", "project_root": "/tmp/project"}, ["room", "instance", "add", "r_main", "o_player", "10", "20", "--layer", "Actors"]),
                ("gm_room_instance_remove", {"room_name": "r_main", "instance_id": "inst_1", "project_root": "/tmp/project"}, ["room", "instance", "remove", "r_main", "inst_1"]),
                ("gm_room_instance_list", {"room_name": "r_main", "project_root": "/tmp/project"}, ["room", "instance", "list", "r_main"]),
            ]

            for tool_name, kwargs, expected_cli in cases:
                result = self.call_tool(tool_name, **kwargs)
                self.assertTrue(result["ok"])
                self.assertEqual(mock_fallback.await_args_list[-1].kwargs["cli_args"], expected_cli)

        with patch("gms_mcp.server.tools.rooms._requires_dry_run_for_tool", return_value=True):
            blocked = self.call_tool(
                "gm_room_ops_delete",
                room_name="r_old",
                dry_run=False,
                project_root="/tmp/project",
            )
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["blocked_by_policy"])


class TestTextureGroupWrappers(MCPToolTestCase):
    module = texture_groups

    def test_texture_group_direct_wrappers_set_project_metadata(self):
        with patch("gms_mcp.server.tools.texture_groups._resolve_project_directory", return_value=Path("/tmp/project")), patch(
            "gms_helpers.texture_groups.load_project_yyp",
            return_value=(Path("/tmp/project/TestGame.yyp"), {}),
        ), patch(
            "gms_helpers.texture_groups.get_project_configs",
            return_value=["desktop"],
        ), patch(
            "gms_helpers.texture_groups.get_texture_groups_list",
            return_value=[{"name": "Default"}],
        ):
            result = self.call_tool("gm_texture_group_list", project_root="/tmp/project")
        self.assertTrue(result["ok"])
        self.assertEqual(result["yyp"], "TestGame.yyp")
        self.assertEqual(result["count"], 1)

        with patch("gms_mcp.server.tools.texture_groups._resolve_project_directory", return_value=Path("/tmp/project")), patch(
            "gms_helpers.texture_groups.load_project_yyp",
            return_value=(Path("/tmp/project/TestGame.yyp"), {}),
        ), patch(
            "gms_helpers.texture_groups.find_texture_group",
            return_value=None,
        ):
            missing = self.call_tool("gm_texture_group_read", name="missing", project_root="/tmp/project")
        self.assertFalse(missing["ok"])
        self.assertIn("not found", missing["error"].lower())

        success_cases = [
            ("gm_texture_group_members", {"group_name": "Default", "asset_types": ["sprite"], "configs": ["desktop"], "project_root": "/tmp/project"}, "gms_helpers.texture_groups.texture_group_members"),
            ("gm_texture_group_scan", {"asset_types": ["sprite"], "configs": ["desktop"], "include_assets": True, "project_root": "/tmp/project"}, "gms_helpers.texture_groups.texture_group_scan"),
            ("gm_texture_group_create", {"name": "game", "template": "Default", "patch": {"autocrop": False}, "dry_run": True, "project_root": "/tmp/project"}, "gms_helpers.texture_groups.texture_group_create"),
            ("gm_texture_group_update", {"name": "game", "patch": {"autocrop": False}, "configs": ["desktop"], "dry_run": True, "project_root": "/tmp/project"}, "gms_helpers.texture_groups.texture_group_update"),
            ("gm_texture_group_rename", {"old_name": "old", "new_name": "new", "dry_run": True, "project_root": "/tmp/project"}, "gms_helpers.texture_groups.texture_group_rename"),
            ("gm_texture_group_delete", {"name": "old", "dry_run": True, "project_root": "/tmp/project"}, "gms_helpers.texture_groups.texture_group_delete"),
            ("gm_texture_group_assign", {"group_name": "game", "asset_identifiers": ["sprites/spr_test/spr_test.yy"], "dry_run": True, "project_root": "/tmp/project"}, "gms_helpers.texture_groups.texture_group_assign"),
        ]

        for tool_name, kwargs, patch_target in success_cases:
            with patch("gms_mcp.server.tools.texture_groups._resolve_project_directory", return_value=Path("/tmp/project")), patch(
                "gms_helpers.texture_groups.load_project_yyp",
                return_value=(Path("/tmp/project/TestGame.yyp"), {}),
            ), patch(
                patch_target,
                return_value={"ok": True},
            ):
                result = self.call_tool(tool_name, **kwargs)
            self.assertTrue(result["ok"])
            self.assertEqual(result["project_directory"].replace("\\", "/"), "/tmp/project")
            self.assertEqual(result["yyp"], "TestGame.yyp")

        with patch("gms_mcp.server.tools.texture_groups._requires_dry_run_for_tool", return_value=True):
            for tool_name, kwargs in [
                ("gm_texture_group_create", {"name": "game", "dry_run": False, "project_root": "/tmp/project"}),
                ("gm_texture_group_update", {"name": "game", "patch": {"autocrop": False}, "dry_run": False, "project_root": "/tmp/project"}),
                ("gm_texture_group_rename", {"old_name": "old", "new_name": "new", "dry_run": False, "project_root": "/tmp/project"}),
                ("gm_texture_group_delete", {"name": "old", "dry_run": False, "project_root": "/tmp/project"}),
                ("gm_texture_group_assign", {"group_name": "game", "dry_run": False, "project_root": "/tmp/project"}),
            ]:
                result = self.call_tool(tool_name, **kwargs)
                self.assertFalse(result["ok"])
                self.assertTrue(result["blocked_by_policy"])


class TestWorkflowWrappers(MCPToolTestCase):
    module = workflow

    def test_workflow_and_sprite_frame_wrappers_forward_cli_args(self):
        with patch(
            "gms_mcp.server.tools.workflow._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as mock_fallback:
            cases = [
                ("gm_workflow_duplicate", {"asset_path": "scripts/scr_old/scr_old.yy", "new_name": "scr_new", "yes": True, "project_root": "/tmp/project"}, ["workflow", "duplicate", "scripts/scr_old/scr_old.yy", "scr_new", "--yes"]),
                ("gm_workflow_rename", {"asset_path": "scripts/scr_old/scr_old.yy", "new_name": "scr_new", "project_root": "/tmp/project"}, ["workflow", "rename", "scripts/scr_old/scr_old.yy", "scr_new"]),
                ("gm_workflow_delete", {"asset_path": "scripts/scr_old/scr_old.yy", "dry_run": True, "project_root": "/tmp/project"}, ["workflow", "delete", "scripts/scr_old/scr_old.yy", "--dry-run"]),
                ("gm_workflow_swap_sprite", {"asset_path": "sprites/spr_test/spr_test.yy", "png": "frame.png", "frame": 2, "project_root": "/tmp/project"}, ["workflow", "swap-sprite", "sprites/spr_test/spr_test.yy", "frame.png", "--frame", "2"]),
                ("gm_sprite_add_frame", {"sprite_path": "sprites/spr_test/spr_test.yy", "position": 2, "source_png": "frame.png", "project_root": "/tmp/project"}, ["sprite-frames", "add", "sprites/spr_test/spr_test.yy", "--position", "2", "--source", "frame.png"]),
                ("gm_sprite_remove_frame", {"sprite_path": "sprites/spr_test/spr_test.yy", "position": 1, "project_root": "/tmp/project"}, ["sprite-frames", "remove", "sprites/spr_test/spr_test.yy", "1"]),
                ("gm_sprite_duplicate_frame", {"sprite_path": "sprites/spr_test/spr_test.yy", "source_position": 0, "target_position": 3, "project_root": "/tmp/project"}, ["sprite-frames", "duplicate", "sprites/spr_test/spr_test.yy", "0", "--target", "3"]),
                ("gm_sprite_import_strip", {"name": "spr_strip", "source": "strip.png", "parent_path": "folders/Sprites.yy", "layout": "grid", "frame_width": 32, "frame_height": 32, "columns": 4, "project_root": "/tmp/project"}, ["sprite-frames", "import-strip", "spr_strip", "strip.png", "--parent-path", "folders/Sprites.yy", "--layout", "grid", "--frame-width", "32", "--frame-height", "32", "--columns", "4"]),
                ("gm_sprite_frame_count", {"sprite_path": "sprites/spr_test/spr_test.yy", "project_root": "/tmp/project"}, ["sprite-frames", "count", "sprites/spr_test/spr_test.yy"]),
            ]

            for tool_name, kwargs, expected_cli in cases:
                result = self.call_tool(tool_name, **kwargs)
                self.assertTrue(result["ok"])
                self.assertEqual(mock_fallback.await_args_list[-1].kwargs["cli_args"], expected_cli)

        with patch("gms_mcp.server.tools.workflow._requires_dry_run_for_tool", return_value=True):
            blocked = self.call_tool(
                "gm_workflow_delete",
                asset_path="scripts/scr_old/scr_old.yy",
                dry_run=False,
                project_root="/tmp/project",
            )
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["blocked_by_policy"])

    def test_safe_delete_uses_policy_and_helper_result(self):
        with patch("gms_mcp.server.tools.workflow._requires_dry_run_for_tool", return_value=True):
            blocked = self.call_tool(
                "gm_safe_delete",
                asset_type="script",
                asset_name="scr_old",
                dry_run=False,
                project_root="/tmp/project",
            )
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["blocked_by_policy"])

        with patch(
            "gms_helpers.workflow.safe_delete_asset",
            return_value={"ok": True, "deleted": True, "dry_run": True},
        ):
            result = self.call_tool(
                "gm_safe_delete",
                asset_type="script",
                asset_name="scr_old",
                clean_refs=True,
                dry_run=True,
                project_root="/tmp/project",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])


class TestRunnerWrappers(MCPToolTestCase):
    module = runner

    def test_compile_and_foreground_run_use_fallback(self):
        with patch(
            "gms_mcp.server.tools.runner._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as mock_fallback:
            compile_result = self.call_tool(
                "gm_compile",
                platform="macOS",
                runtime="YYC",
                runtime_version="2024.11",
                project_root="/tmp/project",
            )
            self.assertTrue(compile_result["ok"])
            self.assertEqual(
                mock_fallback.await_args_list[0].kwargs["cli_args"],
                ["run", "compile", "--platform", "macOS", "--runtime", "YYC", "--runtime-version", "2024.11"],
            )

            run_result = self.call_tool(
                "gm_run",
                platform="macOS",
                runtime="VM",
                background=False,
                output_location="project",
                project_root="/tmp/project",
            )
            self.assertTrue(run_result["ok"])
            self.assertEqual(
                mock_fallback.await_args_list[1].kwargs["cli_args"],
                ["run", "start", "--platform", "macOS", "--runtime", "VM", "--output-location", "project"],
            )

    def test_background_run_and_status_paths(self):
        fake_bridge_server = MagicMock()
        fake_bridge_server.start.return_value = True
        fake_bridge_server.port = 6502

        with patch(
            "gms_mcp.server.tools.runner._capture_output",
            return_value=(True, "", "", {"ok": True, "message": "Game launched"}, None, None),
        ), patch("gms_helpers.bridge_installer.is_bridge_installed", return_value=True), patch(
            "gms_helpers.bridge_server.get_bridge_server",
            return_value=fake_bridge_server,
        ):
            result = self.call_tool(
                "gm_run",
                platform="macOS",
                runtime="VM",
                background=True,
                project_root="/tmp/project",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["bridge_enabled"])
        self.assertEqual(result["bridge_port"], 6502)

        fake_bridge_server.reset_mock()
        fake_bridge_server.start.return_value = True
        with patch(
            "gms_mcp.server.tools.runner._capture_output",
            return_value=(True, "", "", None, "launch failed", None),
        ), patch("gms_helpers.bridge_installer.is_bridge_installed", return_value=True), patch(
            "gms_helpers.bridge_server.get_bridge_server",
            return_value=fake_bridge_server,
        ):
            error_result = self.call_tool(
                "gm_run",
                platform="macOS",
                runtime="VM",
                background=True,
                project_root="/tmp/project",
            )
        self.assertFalse(error_result["ok"])
        fake_bridge_server.stop.assert_called_once()

        with patch("gms_helpers.bridge_server.stop_bridge_server") as mock_stop_bridge, patch(
            "gms_mcp.server.tools.runner._capture_output",
            return_value=(True, "", "", {"ok": True, "message": "Stopped"}, None, None),
        ):
            stop_result = self.call_tool("gm_run_stop", project_root="/tmp/project")
        self.assertTrue(stop_result["ok"])
        self.assertTrue(stop_result["bridge_stopped"])
        mock_stop_bridge.assert_called_once()

        with patch("gms_mcp.server.tools.runner._capture_output", return_value=(True, "", "", None, "status failed", None)):
            status_error = self.call_tool("gm_run_status", project_root="/tmp/project")
        self.assertFalse(status_error["ok"])
        self.assertIn("status failed", status_error["message"])

        with patch("gms_mcp.server.tools.runner._capture_output", return_value=(True, "", "", True, None, None)):
            status_bool = self.call_tool("gm_run_status", project_root="/tmp/project")
        self.assertTrue(status_bool["ok"])
        self.assertTrue(status_bool["running"])


if __name__ == "__main__":
    unittest.main()
