#!/usr/bin/env python3
import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gms_mcp.server.results import unwrap_call_tool_result


def _create_basic_gamemaker_project(project_root: Path, *, name: str = "TestProject") -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    # Asset helper validation requires at least one standard asset directory to exist.
    for d in ("objects", "sprites", "scripts", "rooms", "texturegroups"):
        (project_root / d).mkdir(parents=True, exist_ok=True)

    yyp_path = project_root / f"{name}.yyp"
    yyp_data = {
        "$GMProject": "",
        "%Name": name,
        "name": name,
        "resources": [],
        "folders": [],
        "resourceType": "GMProject",
        "resourceVersion": "2.0",
        "configs": {
            "name": "Default",
            "children": [
                {"name": "desktop", "children": []},
            ],
        },
        "TextureGroups": [
            {
                "$GMTextureGroup": "",
                "%Name": "Default",
                "name": "Default",
                "resourceType": "GMTextureGroup",
                "resourceVersion": "2.0",
                "ConfigValues": {},
            }
        ],
    }
    yyp_path.write_text(json.dumps(yyp_data, indent=2), encoding="utf-8")
    return yyp_path


def _hold_direct_worker(args):
    Path(args.entered_path).write_text(str(Path.cwd()), encoding="utf-8")
    deadline = time.monotonic() + 5
    while not Path(args.release_path).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not Path(args.release_path).exists():
        raise TimeoutError("direct worker was not released")
    return True


class TestMCPIntegrationTools(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temp_dir.name)
        _create_basic_gamemaker_project(self.project_root)
        self._previous_verify_mode = os.environ.get("GMS_MCP_POST_MUTATION_VERIFY")
        self._previous_toolsets = os.environ.get("GMS_MCP_TOOLSETS")
        self._previous_project_root = os.environ.get("GM_PROJECT_ROOT")
        os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = "off"
        os.environ["GMS_MCP_TOOLSETS"] = "all"
        os.environ["GM_PROJECT_ROOT"] = str(self.project_root)

        from gms_mcp.gamemaker_mcp_server import build_server

        self.mcp = build_server()

    def tearDown(self):
        if self._previous_verify_mode is None:
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
        else:
            os.environ["GMS_MCP_POST_MUTATION_VERIFY"] = self._previous_verify_mode
        if self._previous_toolsets is None:
            os.environ.pop("GMS_MCP_TOOLSETS", None)
        else:
            os.environ["GMS_MCP_TOOLSETS"] = self._previous_toolsets
        if self._previous_project_root is None:
            os.environ.pop("GM_PROJECT_ROOT", None)
        else:
            os.environ["GM_PROJECT_ROOT"] = self._previous_project_root
        try:
            self._temp_dir.cleanup()
        except Exception:
            pass

    def _call_tool(self, tool_name: str, arguments: dict):
        out = asyncio.run(self.mcp.call_tool(tool_name, arguments))
        return unwrap_call_tool_result(out)

    def test_list_tools_includes_core_entries(self):
        tools = asyncio.run(self.mcp.list_tools())
        names = {t.name for t in tools}

        # Sanity checks: these are stable, core tools.
        self.assertIn("gm_project_info", names)
        self.assertIn("gm_list_assets", names)
        self.assertIn("gm_create_script", names)
        self.assertIn("gm_texture_group_list", names)

    def test_call_gm_project_info_through_server(self):
        # Avoid network in tests (PyPI update check).
        with patch(
            "gms_mcp.server.tools.project_health.get_update_status",
            return_value=SimpleNamespace(to_dict=lambda: {"update_available": False, "status": "ok"}),
        ):
            out = asyncio.run(
                self.mcp.call_tool(
                    "gm_project_info",
                    {"project_root": str(self.project_root)},
                )
            )
        result = unwrap_call_tool_result(out)

        self.assertEqual(result.get("yyp"), "TestProject.yyp")
        self.assertEqual(result["project_directory"], ".")

    def test_call_asset_create_and_list_assets_through_server(self):
        out = asyncio.run(
            self.mcp.call_tool(
                "gm_create_script",
                {"name": "scr_utils", "project_root": str(self.project_root)},
            )
        )
        result = unwrap_call_tool_result(out)
        self.assertTrue(result.get("ok"), msg=result.get("error") or result.get("stderr") or result.get("stdout"))

        # Confirm files were actually created in the project.
        self.assertTrue((self.project_root / "scripts" / "scr_utils" / "scr_utils.yy").exists())
        self.assertTrue((self.project_root / "scripts" / "scr_utils" / "scr_utils.gml").exists())
        from gms_helpers.utils import load_json_loose

        script_data = load_json_loose(self.project_root / "scripts" / "scr_utils" / "scr_utils.yy")
        project_data = load_json_loose(self.project_root / "TestProject.yyp")
        parent_path = script_data["parent"]["path"]
        self.assertEqual(parent_path, "folders/Scripts.yy")
        self.assertNotEqual(parent_path, "TestProject.yyp")
        self.assertIn(parent_path, {folder["folderPath"] for folder in project_data["Folders"]})

        from gms_helpers.transactions import validate_project_after_mutation

        self.assertTrue(validate_project_after_mutation(self.project_root).success)

        out = asyncio.run(
            self.mcp.call_tool(
                "gm_list_assets",
                {"asset_type": "script", "project_root": str(self.project_root)},
            )
        )
        assets_result = unwrap_call_tool_result(out)
        self.assertGreaterEqual(int(assets_result.get("count", 0)), 1)
        scripts = (assets_result.get("assets") or {}).get("script") or []
        self.assertTrue(any(a.get("name") == "scr_utils" for a in scripts), msg=str(scripts))
        self.assertIn("transaction", result)
        self.assertTrue(result["transaction"]["committed"])

    def test_collision_events_work_end_to_end_through_mcp(self):
        for object_name in ("o_player", "o_enemy", "o_wall"):
            created = self._call_tool(
                "gm_create_object",
                {"name": object_name, "project_root": str(self.project_root)},
            )
            self.assertTrue(created.get("ok"), msg=created)

        source = self._call_tool(
            "gm_event_add",
            {
                "object": "o_player",
                "event": "collision:o_enemy",
                "template": "// collision source\n",
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(source.get("ok"), msg=source)

        duplicated = self._call_tool(
            "gm_event_duplicate",
            {
                "object": "o_player",
                "source_event": "collision:o_enemy",
                "target_event": "collision:o_wall",
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(duplicated.get("ok"), msg=duplicated)

        collision_path = self.project_root / "objects" / "o_player" / "Collision_o_wall.gml"
        self.assertEqual(collision_path.read_text(encoding="utf-8"), "// collision source\n")
        from gms_helpers.utils import load_json_loose

        object_data = load_json_loose(self.project_root / "objects" / "o_player" / "o_player.yy")
        wall_event = next(
            event
            for event in object_data["eventList"]
            if isinstance(event.get("collisionObjectId"), dict) and event["collisionObjectId"].get("name") == "o_wall"
        )
        self.assertEqual(
            wall_event["collisionObjectId"],
            {"name": "o_wall", "path": "objects/o_wall/o_wall.yy"},
        )

        listed = self._call_tool(
            "gm_event_list",
            {"object": "o_player", "project_root": str(self.project_root)},
        )
        self.assertTrue(listed.get("ok"), msg=listed)
        self.assertIn("Collision_o_wall.gml", listed.get("stdout", ""))

        numeric = self._call_tool(
            "gm_event_add",
            {
                "object": "o_player",
                "event": "collision:0",
                "project_root": str(self.project_root),
            },
        )
        self.assertFalse(numeric["ok"])
        self.assertEqual(numeric["error"], "Invalid MCP tool arguments")

        removed = self._call_tool(
            "gm_event_remove",
            {
                "object": "o_player",
                "event": "collision:o_wall",
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(removed.get("ok"), msg=removed)
        self.assertFalse(collision_path.exists())

    def test_explicit_parent_path_is_validated_and_preserved_through_mcp(self):
        folder = self._call_tool(
            "gm_create_folder",
            {
                "name": "Gameplay",
                "path": "folders/Gameplay.yy",
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(folder.get("ok"), msg=folder)

        created = self._call_tool(
            "gm_create_object",
            {
                "name": "o_explicit_parent",
                "parent_path": "folders/Gameplay.yy",
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(created.get("ok"), msg=created)

        from gms_helpers.utils import load_json_loose

        object_data = load_json_loose(self.project_root / "objects" / "o_explicit_parent" / "o_explicit_parent.yy")
        self.assertEqual(object_data["parent"]["path"], "folders/Gameplay.yy")

        rejected = self._call_tool(
            "gm_create_object",
            {
                "name": "o_missing_parent",
                "parent_path": "folders/Missing.yy",
                "project_root": str(self.project_root),
            },
        )
        self.assertFalse(rejected["ok"])
        self.assertTrue(any(error["field"] == "parent_path" for error in rejected["validation_errors"]))
        self.assertFalse((self.project_root / "objects" / "o_missing_parent").exists())

    def test_mcp_boundary_rejects_path_like_resource_names(self):
        result = self._call_tool(
            "gm_create_script",
            {"name": "../scr_escape", "project_root": str(self.project_root)},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Invalid MCP tool arguments")
        self.assertTrue(result["validation_errors"])
        self.assertFalse((self.project_root / "scripts" / "scr_escape").exists())

    def test_mcp_boundary_rejects_domain_invalid_asset_name_before_write(self):
        result = self._call_tool(
            "gm_create_object",
            {"name": "player", "project_root": str(self.project_root)},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Invalid MCP tool arguments")
        self.assertTrue(any(error["field"] == "name" for error in result["validation_errors"]))
        self.assertNotIn("transaction", result)
        self.assertFalse((self.project_root / "objects" / "player").exists())

    def test_mcp_boundary_rejects_invalid_safe_delete_name_before_transaction(self):
        result = self._call_tool(
            "gm_safe_delete",
            {
                "asset_type": "script",
                "asset_name": "../scr_escape",
                "dry_run": True,
                "project_root": str(self.project_root),
            },
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Invalid MCP tool arguments")
        self.assertTrue(any(error["field"] == "asset_name" for error in result["validation_errors"]))
        self.assertNotIn("transaction", result)

    def test_default_project_root_cannot_follow_another_direct_calls_cwd(self):
        from gms_mcp.server.direct import _run_direct

        other_temp = tempfile.TemporaryDirectory()
        self.addCleanup(other_temp.cleanup)
        other_root = Path(other_temp.name)
        _create_basic_gamemaker_project(other_root, name="OtherProject")
        created = self._call_tool(
            "gm_create_script",
            {"name": "scr_target", "project_root": str(self.project_root)},
        )
        self.assertTrue(created["ok"])
        denied = self._call_tool(
            "gm_create_script",
            {"name": "scr_target", "project_root": str(other_root)},
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error_type"], "ProjectAccessError")
        self.assertNotIn(str(other_root), json.dumps(denied))

        direct_entered = self.project_root.parent / "direct-entered"
        release_direct = self.project_root.parent / "release-direct"

        direct_thread = threading.Thread(
            target=_run_direct,
            args=(
                _hold_direct_worker,
                SimpleNamespace(
                    entered_path=str(direct_entered),
                    release_path=str(release_direct),
                ),
                str(other_root),
            ),
        )
        direct_thread.start()
        deadline = time.monotonic() + 5
        while not direct_entered.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(direct_entered.exists())
        try:
            with patch.dict(os.environ, {"GM_PROJECT_ROOT": str(self.project_root)}, clear=False):
                deleted = self._call_tool(
                    "gm_safe_delete",
                    {
                        "asset_type": "script",
                        "asset_name": "scr_target",
                        "force": True,
                        "dry_run": False,
                        "project_root": ".",
                    },
                )
        finally:
            release_direct.write_text("release", encoding="utf-8")
            direct_thread.join(timeout=5)

        self.assertTrue(deleted["ok"])
        self.assertEqual(deleted["transaction"]["project_root"], ".")
        self.assertFalse((self.project_root / "scripts" / "scr_target").exists())
        self.assertFalse((other_root / "scripts" / "scr_target").exists())

    def test_health_rejects_an_unapproved_project_without_echoing_its_path(self):
        missing_temp = tempfile.TemporaryDirectory()
        self.addCleanup(missing_temp.cleanup)
        missing_project = Path(missing_temp.name)

        with (
            patch("gms_helpers.runner.GameMakerRunner.find_gamemaker_runtime", return_value=None),
            patch("gms_helpers.runner.GameMakerRunner.find_license_file", return_value=None),
        ):
            result = self._call_tool("gm_mcp_health", {"project_root": str(missing_project)})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ProjectAccessError")
        self.assertNotIn(str(missing_project), json.dumps(result))

    def test_read_asset_rejects_parent_traversal_without_reading_external_content(self):
        private_file = self.project_root.parent / "private.yy"
        private_file.write_text('{"private":"studio-secret-marker"}', encoding="utf-8")

        result = self._call_tool(
            "gm_read_asset",
            {"asset_identifier": "../private.yy", "project_root": "."},
        )

        self.assertFalse(result["ok"])
        self.assertNotIn("studio-secret-marker", json.dumps(result))

    @unittest.skipIf(os.name == "nt", "Symlink containment test requires POSIX symlinks")
    def test_project_symlink_escape_is_rejected_before_a_tool_reads_it(self):
        outside_file = self.project_root.parent / "private-link-target.yy"
        outside_file.write_text('{"private":"symlink-secret-marker"}', encoding="utf-8")
        (self.project_root / "objects" / "private.yy").symlink_to(outside_file)

        result = self._call_tool(
            "gm_read_asset",
            {"asset_identifier": "objects/private.yy", "project_root": "."},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "ProjectAccessError")
        self.assertNotIn("symlink-secret-marker", json.dumps(result))
        self.assertNotIn(str(outside_file), json.dumps(result))

    def test_write_operation_models_cover_core_write_tools(self):
        from gms_mcp.server.validation import write_operation_model_names

        names = set(write_operation_model_names())
        expected = {
            "gm_create_script",
            "gm_create_object",
            "gm_event_add",
            "gm_event_remove",
            "gm_room_layer_add",
            "gm_room_instance_add",
            "gm_safe_delete",
            "gm_workflow_rename",
            "gm_sprite_add_frame",
            "gm_texture_group_update",
            "gm_texture_group_assign",
        }
        self.assertTrue(expected.issubset(names), msg=f"Missing write models: {sorted(expected - names)}")

    def test_failed_mutation_rolls_back_created_files(self):
        yyp_path = self.project_root / "TestProject.yyp"
        yyp_data = json.loads(yyp_path.read_text(encoding="utf-8"))
        yyp_data["resources"].append({"id": {"name": "scr_conflict", "path": "scripts/scr_conflict/scr_conflict.yy"}})
        yyp_path.write_text(json.dumps(yyp_data, indent=2), encoding="utf-8")

        result = self._call_tool(
            "gm_create_script",
            {"name": "scr_conflict", "project_root": str(self.project_root)},
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["transaction"]["rolled_back"])
        self.assertFalse((self.project_root / "scripts" / "scr_conflict").exists())

    def test_smart_verification_compiles_high_risk_mutation_immediately(self):
        fake_compile = {
            "ok": True,
            "mode": "compile",
            "platform": "macOS",
            "runtime": "VM",
            "exit_code": 0,
            "elapsed_seconds": 0.01,
            "stdout_tail": "",
            "stderr_tail": "",
        }

        with (
            patch.dict(
                os.environ,
                {
                    "GMS_MCP_POST_MUTATION_VERIFY": "smart",
                    "GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION": "0",
                },
                clear=False,
            ),
            patch("gms_helpers.transactions.compile_verify_project", return_value=fake_compile) as compile_mock,
        ):
            result = self._call_tool(
                "gm_create_script",
                {"name": "scr_verified", "project_root": str(self.project_root)},
            )

        self.assertTrue(result.get("ok"), msg=result)
        compile_mock.assert_called_once()
        transaction = result["transaction"]
        self.assertEqual(transaction["verification_policy"]["mode"], "smart")
        self.assertEqual(transaction["verification_policy"]["action"], "compile")
        self.assertTrue(transaction["compile_verification"]["ok"])

    def test_smart_verification_defers_sprite_frame_batch_until_flush(self):
        created = self._call_tool(
            "gm_create_sprite",
            {"name": "spr_batch", "project_root": str(self.project_root)},
        )
        self.assertTrue(created.get("ok"), msg=created)

        with (
            patch.dict(
                os.environ,
                {
                    "GMS_MCP_POST_MUTATION_VERIFY": "smart",
                    "GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION": "0",
                },
                clear=False,
            ),
            patch("gms_helpers.transactions.compile_verify_project") as compile_mock,
        ):
            added = self._call_tool(
                "gm_sprite_add_frame",
                {
                    "sprite_path": "sprites/spr_batch/spr_batch.yy",
                    "project_root": str(self.project_root),
                },
            )
            status = self._call_tool("gm_verification_status", {"project_root": str(self.project_root)})

        self.assertTrue(added.get("ok"), msg=added)
        compile_mock.assert_not_called()
        transaction = added["transaction"]
        self.assertEqual(transaction["verification_policy"]["mode"], "smart")
        self.assertEqual(transaction["verification_policy"]["action"], "defer")
        self.assertEqual(transaction["pending_compile_verification"]["operation_count"], 1)
        self.assertTrue(status["pending_compile_verification"]["required"])

        fake_compile = {
            "ok": True,
            "mode": "compile",
            "platform": "macOS",
            "runtime": "VM",
            "exit_code": 0,
            "elapsed_seconds": 0.01,
            "stdout_tail": "",
            "stderr_tail": "",
        }
        with (
            patch.dict(
                os.environ,
                {
                    "GMS_MCP_POST_MUTATION_VERIFY": "smart",
                    "GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION": "0",
                },
                clear=False,
            ),
            patch(
                "gms_mcp.server.verification_policy.compile_verify_project", return_value=fake_compile
            ) as compile_mock,
        ):
            flushed = self._call_tool("gm_verification_flush", {"project_root": str(self.project_root)})
            status_after = self._call_tool("gm_verification_status", {"project_root": str(self.project_root)})

        self.assertTrue(flushed.get("ok"), msg=flushed)
        self.assertTrue(flushed["compiled"])
        compile_mock.assert_called_once()
        self.assertIsNone(flushed["pending_compile_verification"])
        self.assertIsNone(status_after["pending_compile_verification"])

    def test_tool_registration_parity_includes_critical_categories(self):
        tools = asyncio.run(self.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertGreaterEqual(len(names), 94)

        expected = {
            "gm_project_info",
            "gm_create_script",
            "gm_list_assets",
            "gm_maintenance_validate_json",
            "gm_runtime_list",
            "gm_run_status",
            "gm_bridge_status",
            "gm_doc_categories",
            "gm_event_list",
            "gm_safe_delete",
            "gm_room_ops_list",
            "gm_texture_group_list",
            "gm_texture_group_assign",
            "gm_list_symbols",
        }
        self.assertTrue(expected.issubset(names), msg=f"Missing critical tools: {sorted(expected - names)}")

    def test_smoke_calls_across_tool_categories(self):
        with patch(
            "gms_mcp.server.tools.project_health.get_update_status",
            return_value=SimpleNamespace(to_dict=lambda: {"update_available": False, "status": "ok"}),
        ):
            project_info = self._call_tool("gm_project_info", {"project_root": str(self.project_root)})
        self.assertEqual(project_info.get("yyp"), "TestProject.yyp")

        create_script = self._call_tool(
            "gm_create_script",
            {"name": "scr_utils", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_script.get("ok"), msg=create_script.get("error") or create_script.get("stdout"))

        create_object = self._call_tool(
            "gm_create_object",
            {"name": "o_player", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_object.get("ok"), msg=create_object.get("error") or create_object.get("stdout"))

        create_room = self._call_tool(
            "gm_create_room",
            {"name": "r_main", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_room.get("ok"), msg=create_room.get("error") or create_room.get("stdout"))

        introspection = self._call_tool(
            "gm_list_assets",
            {"asset_type": "script", "project_root": str(self.project_root)},
        )
        self.assertGreaterEqual(int(introspection.get("count", 0)), 1)

        maintenance = self._call_tool(
            "gm_maintenance_validate_json",
            {"project_root": str(self.project_root)},
        )
        self.assertIn("ok", maintenance)

        runtime = self._call_tool(
            "gm_runtime_list",
            {"project_root": str(self.project_root)},
        )
        self.assertIn("count", runtime)
        self.assertIn("runtimes", runtime)

        runner_status = self._call_tool(
            "gm_run_status",
            {"project_root": str(self.project_root)},
        )
        self.assertIn("running", runner_status)
        self.assertIn("has_session", runner_status)

        fake_bridge_server = SimpleNamespace(get_status=lambda: {"running": True, "connected": False, "log_count": 0})
        with (
            patch("gms_helpers.bridge_installer.get_bridge_status", return_value={"installed": True}),
            patch(
                "gms_helpers.bridge_server.get_bridge_server",
                return_value=fake_bridge_server,
            ),
        ):
            bridge_status = self._call_tool(
                "gm_bridge_status",
                {"project_root": str(self.project_root)},
            )
        self.assertTrue(bridge_status.get("ok"))
        self.assertTrue(bridge_status.get("installed"))

        with patch("gms_helpers.gml_docs.list_categories", return_value={"ok": True, "categories": ["Drawing"]}):
            docs = self._call_tool("gm_doc_categories", {})
        self.assertTrue(docs.get("ok"))
        self.assertIn("categories", docs)

        event_add = self._call_tool(
            "gm_event_add",
            {"object": "o_player", "event": "create", "project_root": str(self.project_root)},
        )
        self.assertTrue(event_add.get("ok"), msg=event_add.get("error") or event_add.get("stdout"))

        events = self._call_tool(
            "gm_event_list",
            {"object": "o_player", "project_root": str(self.project_root)},
        )
        self.assertTrue(events.get("ok"), msg=events.get("error") or events.get("stdout"))

        safe_delete = self._call_tool(
            "gm_safe_delete",
            {
                "asset_type": "script",
                "asset_name": "scr_utils",
                "dry_run": True,
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(safe_delete.get("ok"), msg=safe_delete)
        self.assertTrue(safe_delete.get("data", {}).get("dry_run"))

        rooms = self._call_tool(
            "gm_room_ops_list",
            {"project_root": str(self.project_root)},
        )
        self.assertTrue(rooms.get("ok"), msg=rooms.get("error") or rooms.get("stdout"))

        texture_groups = self._call_tool(
            "gm_texture_group_list",
            {"project_root": str(self.project_root)},
        )
        self.assertTrue(texture_groups.get("ok"))
        self.assertGreaterEqual(int(texture_groups.get("count", 0)), 1)

    def test_safe_delete_tool_dry_run_and_apply(self):
        create_target = self._call_tool(
            "gm_create_script",
            {"name": "scr_target", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_target.get("ok"), msg=create_target.get("error") or create_target.get("stdout"))

        create_caller = self._call_tool(
            "gm_create_script",
            {"name": "scr_caller", "project_root": str(self.project_root)},
        )
        self.assertTrue(create_caller.get("ok"), msg=create_caller.get("error") or create_caller.get("stdout"))

        caller_file = self.project_root / "scripts" / "scr_caller" / "scr_caller.gml"
        caller_file.write_text("function scr_caller() {\n    script_execute(scr_target);\n}\n", encoding="utf-8")

        dry_run = self._call_tool(
            "gm_safe_delete",
            {
                "asset_type": "script",
                "asset_name": "scr_target",
                "dry_run": True,
                "project_root": str(self.project_root),
            },
        )
        self.assertFalse(dry_run.get("ok"))
        self.assertTrue(dry_run.get("data", {}).get("blocked"))
        self.assertFalse(dry_run.get("data", {}).get("deleted"))

        applied = self._call_tool(
            "gm_safe_delete",
            {
                "asset_type": "script",
                "asset_name": "scr_target",
                "dry_run": False,
                "force": True,
                "project_root": str(self.project_root),
            },
        )
        self.assertTrue(applied.get("ok"), msg=applied)
        self.assertTrue(applied.get("data", {}).get("deleted"), msg=applied)
        self.assertFalse((self.project_root / "scripts" / "scr_target").exists())
        self.assertIn("scr_target", caller_file.read_text(encoding="utf-8"))

        build_index = self._call_tool(
            "gm_build_index",
            {"project_root": str(self.project_root), "force": True},
        )
        self.assertTrue(build_index.get("ok"), msg=build_index.get("error") or build_index.get("stdout"))

        symbols = self._call_tool(
            "gm_list_symbols",
            {"project_root": str(self.project_root), "max_results": 5},
        )
        self.assertTrue(symbols.get("ok"), msg=symbols.get("error") or symbols.get("stdout"))

    def test_workflow_rename_reuses_parent_transaction_without_nested_lock(self):
        created = self._call_tool(
            "gm_create_script",
            {"name": "scr_before", "project_root": str(self.project_root)},
        )
        self.assertTrue(created.get("ok"), msg=created)

        renamed = self._call_tool(
            "gm_workflow_rename",
            {
                "asset_path": "scripts/scr_before/scr_before.yy",
                "new_name": "scr_after",
                "project_root": str(self.project_root),
            },
        )

        self.assertTrue(renamed.get("ok"), msg=renamed)
        self.assertTrue(renamed.get("transaction", {}).get("committed"), msg=renamed)
        self.assertFalse((self.project_root / "scripts" / "scr_before").exists())
        self.assertTrue((self.project_root / "scripts" / "scr_after" / "scr_after.yy").exists())


if __name__ == "__main__":
    unittest.main()
