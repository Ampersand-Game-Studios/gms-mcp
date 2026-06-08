#!/usr/bin/env python3
"""Regression coverage for MCP argument validation models."""

from __future__ import annotations

import unittest

from gms_mcp.server.validation import invalid_arguments_result, validate_mcp_tool_arguments, write_operation_model_names


def _fields(errors):
    return {error["field"] for error in errors}


class TestMCPValidationModels(unittest.TestCase):
    def test_write_model_registry_includes_mutation_surfaces(self):
        names = set(write_operation_model_names())

        expected = {
            "gm_asset_delete",
            "gm_create_object",
            "gm_event_add",
            "gm_room_instance_add",
            "gm_safe_delete",
            "gm_sprite_import_strip",
            "gm_texture_group_assign",
            "gm_workflow_delete",
            "gm_workflow_swap_sprite",
        }

        self.assertTrue(expected.issubset(names), msg=f"Missing write models: {sorted(expected - names)}")

    def test_asset_create_model_rejects_bad_domain_values(self):
        errors = validate_mcp_tool_arguments(
            "gm_create_sound",
            {
                "name": "boom",
                "parent_path": "C:\\Game\\folders\\Sounds.yy",
                "sound_type": 9,
                "format": "mp3",
                "volume": 1.5,
                "pitch": float("inf"),
                "bitrate": 0,
                "sample_rate": "fast",
                "skip_maintenance": "yes",
                "tail_lines": -1,
            },
        )

        fields = _fields(errors)
        self.assertIn("name", fields)
        self.assertIn("parent_path", fields)
        self.assertIn("sound_type", fields)
        self.assertIn("format", fields)
        self.assertIn("volume", fields)
        self.assertIn("pitch", fields)
        self.assertIn("bitrate", fields)
        self.assertIn("sample_rate", fields)
        self.assertIn("skip_maintenance", fields)
        self.assertIn("tail_lines", fields)

    def test_folder_and_asset_paths_are_validated_before_write(self):
        folder_errors = validate_mcp_tool_arguments(
            "gm_create_folder",
            {"name": "../Bad", "path": "../folders/Bad.yy"},
        )
        workflow_errors = validate_mcp_tool_arguments(
            "gm_workflow_swap_sprite",
            {"asset_path": "objects/o_player/o_player.yy", "png": "sprite.jpg", "frame": -1},
        )

        self.assertIn("name", _fields(folder_errors))
        self.assertIn("path", _fields(folder_errors))
        self.assertIn("asset_path", _fields(workflow_errors))
        self.assertIn("png", _fields(workflow_errors))
        self.assertIn("frame", _fields(workflow_errors))

    def test_event_and_texture_group_models_validate_structured_inputs(self):
        event_errors = validate_mcp_tool_arguments(
            "gm_event_duplicate",
            {"object": "objects/o_player/o_player.yy", "source_event": "step:not_int", "target_num": True},
        )
        texture_errors = validate_mcp_tool_arguments(
            "gm_texture_group_update",
            {"name": "texturegroups/Default", "patch": ["bad"], "configs": ["desktop", ""], "dry_run": None},
        )
        assign_errors = validate_mcp_tool_arguments(
            "gm_texture_group_assign",
            {
                "group_name": "Default",
                "asset_type": "bogus",
                "asset_identifiers": ["spr_ok", "../bad", "C:\\bad\\asset.yy"],
                "name_contains": 123,
                "folder_prefix": "   ",
            },
        )

        self.assertIn("object", _fields(event_errors))
        self.assertIn("source_event", _fields(event_errors))
        self.assertIn("target_num", _fields(event_errors))
        self.assertIn("name", _fields(texture_errors))
        self.assertIn("patch", _fields(texture_errors))
        self.assertIn("configs[1]", _fields(texture_errors))
        self.assertIn("asset_type", _fields(assign_errors))
        self.assertIn("asset_identifiers[1]", _fields(assign_errors))
        self.assertIn("asset_identifiers[2]", _fields(assign_errors))
        self.assertIn("name_contains", _fields(assign_errors))
        self.assertIn("folder_prefix", _fields(assign_errors))

    def test_legacy_generic_validation_still_covers_read_tools(self):
        errors = validate_mcp_tool_arguments(
            "gm_find_references",
            {
                "symbol_name": "../scr_bad",
                "scope": "binary",
                "runtime": "GMRT",
                "platform": "BeOS",
                "max_results": 0,
                "depth": -1,
                "output_mode": "verbose",
                "timeout_seconds": "forever",
            },
        )

        fields = _fields(errors)
        self.assertIn("symbol_name", fields)
        self.assertIn("scope", fields)
        self.assertIn("runtime", fields)
        self.assertIn("platform", fields)
        self.assertIn("max_results", fields)
        self.assertIn("depth", fields)
        self.assertIn("output_mode", fields)
        self.assertIn("timeout_seconds", fields)

    def test_invalid_arguments_result_shape(self):
        result = invalid_arguments_result("gm_create_object", [{"field": "name", "message": "bad"}])

        self.assertFalse(result["ok"])
        self.assertEqual(result["tool"], "gm_create_object")
        self.assertEqual(result["error"], "Invalid MCP tool arguments")
        self.assertEqual(result["validation_errors"][0]["field"], "name")


if __name__ == "__main__":
    unittest.main()
