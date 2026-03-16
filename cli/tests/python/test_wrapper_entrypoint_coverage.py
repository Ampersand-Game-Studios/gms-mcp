#!/usr/bin/env python3
"""Coverage tests for wrapper and entrypoint modules."""

from __future__ import annotations

import asyncio
import io
import os
import runpy
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers import cli as helpers_cli
from gms_helpers.commands import (
    asset_commands,
    event_commands,
    maintenance_commands,
    room_commands,
    runner_commands,
    workflow_commands,
)
from gms_mcp import bootstrap_server, cli as mcp_cli, gamemaker_mcp_server
from gms_mcp.server import output as server_output
from gms_mcp.server import platform as server_platform
from gms_mcp.server import project as server_project
from gms_mcp.server import resources as server_resources
from gms_mcp.server.tools import (
    code_intel,
    docs as docs_tools,
    events as event_tools,
    introspection as introspection_tools,
    project_health,
    runtime as runtime_tools,
)


def _capture_output(func, *args, **kwargs):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = func(*args, **kwargs)
    return result, stdout.getvalue(), stderr.getvalue()


class FakeMCP:
    def __init__(self):
        self.tools = {}
        self.resources = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def resource(self, uri):
        def decorator(func):
            self.resources[uri] = func
            return func

        return decorator


class MCPToolTestCase(unittest.TestCase):
    module = None

    def setUp(self):
        self.mcp = FakeMCP()
        self.module.register(self.mcp, object)

    def call_tool(self, tool_name: str, **kwargs):
        return asyncio.run(self.mcp.tools[tool_name](**kwargs))

    def call_resource(self, uri: str):
        return asyncio.run(self.mcp.resources[uri]())


class TestEntrypoints(unittest.TestCase):
    def test_gms_helpers_cli_exits_with_underlying_result(self):
        with patch("gms_helpers.gms.main", return_value=True):
            with self.assertRaises(SystemExit) as exc:
                helpers_cli.main()
        self.assertEqual(exc.exception.code, 0)

        with patch("gms_helpers.gms.main", return_value=False):
            with self.assertRaises(SystemExit) as exc:
                helpers_cli.main()
        self.assertEqual(exc.exception.code, 1)

    def test_gms_helpers_main_module_calls_cli(self):
        with patch("gms_helpers.cli.main") as mock_main:
            runpy.run_module("gms_helpers.__main__", run_name="__main__")
        mock_main.assert_called_once()

    def test_mcp_cli_server_and_init_raise_system_exit(self):
        with patch("gms_mcp.gamemaker_mcp_server.main", return_value=2):
            with self.assertRaises(SystemExit) as exc:
                mcp_cli.server()
        self.assertEqual(exc.exception.code, 2)

        with patch("gms_mcp.install.main", return_value=None):
            with self.assertRaises(SystemExit) as exc:
                mcp_cli.init()
        self.assertEqual(exc.exception.code, 0)

    def test_mcp_cli_main_dispatches_commands(self):
        with patch("gms_mcp.cli._server_main", return_value=7):
            self.assertEqual(mcp_cli.main([]), 7)
            self.assertEqual(mcp_cli.main(["server"]), 7)

        with patch("gms_mcp.doctor.main", return_value=3) as doctor_main:
            self.assertEqual(mcp_cli.main(["doctor", "--json"]), 3)
        doctor_main.assert_called_once_with(["--json"])

        with patch("gms_mcp.install.main", return_value=5):
            self.assertEqual(mcp_cli.main(["init", "--codex"]), 5)

        code, stdout, stderr = _capture_output(mcp_cli.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage: gms-mcp", stdout)
        self.assertEqual(stderr, "")

        code, stdout, stderr = _capture_output(mcp_cli.main, ["bogus"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Unknown command: bogus", stderr)

    def test_mcp_main_module_calls_main(self):
        with patch("gms_mcp.cli.main", return_value=0) as mock_main:
            with self.assertRaises(SystemExit) as exc:
                runpy.run_module("gms_mcp.__main__", run_name="__main__")
        self.assertEqual(exc.exception.code, 0)
        mock_main.assert_called_once()

    def test_bootstrap_server_main_success_and_missing_dependency(self):
        with patch("gms_mcp.bootstrap_server._dbg"), patch(
            "gms_mcp.gamemaker_mcp_server.main", return_value=0
        ):
            result = bootstrap_server.main()
        self.assertEqual(result, 0)

        original_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.endswith("gamemaker_mcp_server"):
                raise ModuleNotFoundError("missing mcp")
            return original_import(name, globals, locals, fromlist, level)

        stderr = io.StringIO()
        with patch("builtins.__import__", side_effect=fake_import), patch("gms_mcp.bootstrap_server._dbg"), redirect_stderr(stderr):
            result = bootstrap_server.main()
        self.assertEqual(result, 1)
        self.assertIn("Missing dependency while starting the GameMaker MCP server", stderr.getvalue())

    def test_gamemaker_mcp_server_build_and_main(self):
        fake_fastmcp_mod = types.ModuleType("mcp.server.fastmcp")

        class FakeContext:
            pass

        class FakeFastMCP:
            def __init__(self, name):
                self.name = name

            def run(self):
                self.ran = True

        fake_fastmcp_mod.Context = FakeContext
        fake_fastmcp_mod.FastMCP = FakeFastMCP

        with patch.dict(sys.modules, {"mcp.server.fastmcp": fake_fastmcp_mod}), patch(
            "gms_mcp.gamemaker_mcp_server.register_all"
        ) as register_all, patch("gms_mcp.gamemaker_mcp_server._dbg"):
            server = gamemaker_mcp_server.build_server()
        self.assertEqual(server.name, "GameMaker MCP")
        register_all.assert_called_once_with(server, FakeContext)

        class FakeServerClass:
            _gms_mcp_patched = False

            async def _handle_request(self, message, req, session, lifespan_context, raise_exceptions):
                return "ok"

        fake_lowlevel_mod = types.ModuleType("mcp.server.lowlevel.server")
        fake_lowlevel_mod.Server = FakeServerClass
        fake_mcp = types.ModuleType("mcp")
        fake_mcp_server = types.ModuleType("mcp.server")
        fake_mcp_lowlevel = types.ModuleType("mcp.server.lowlevel")

        run_server = Mock()
        with patch(
            "gms_mcp.gamemaker_mcp_server.build_server",
            return_value=SimpleNamespace(run=run_server),
        ), patch("gms_mcp.gamemaker_mcp_server._dbg"), patch.dict(
            sys.modules,
            {
                "mcp": fake_mcp,
                "mcp.server": fake_mcp_server,
                "mcp.server.lowlevel": fake_mcp_lowlevel,
                "mcp.server.lowlevel.server": fake_lowlevel_mod,
            },
        ):
            result = gamemaker_mcp_server.main()
        self.assertEqual(result, 0)
        run_server.assert_called_once()
        self.assertTrue(FakeServerClass._gms_mcp_patched)

        stderr = io.StringIO()
        with patch("gms_mcp.gamemaker_mcp_server.build_server", side_effect=ModuleNotFoundError("mcp")), redirect_stderr(stderr):
            result = gamemaker_mcp_server.main()
        self.assertEqual(result, 1)
        self.assertIn("MCP dependency is missing", stderr.getvalue())


class TestCommandWrappers(unittest.TestCase):
    def test_asset_commands_route_and_reject_unknown_types(self):
        mapping = {
            "script": "create_script",
            "object": "create_object",
            "sprite": "create_sprite",
            "room": "create_room",
            "folder": "create_folder",
            "font": "create_font",
            "shader": "create_shader",
            "animcurve": "create_animcurve",
            "sound": "create_sound",
            "path": "create_path",
            "tileset": "create_tileset",
            "timeline": "create_timeline",
            "sequence": "create_sequence",
            "note": "create_note",
        }
        for asset_type, target in mapping.items():
            args = SimpleNamespace(asset_type=asset_type)
            with self.subTest(asset_type=asset_type), patch.object(asset_commands, target, return_value=True) as handler:
                self.assertTrue(asset_commands.handle_asset_create(args))
                handler.assert_called_once_with(args)

        with patch("builtins.print") as print_mock:
            self.assertFalse(asset_commands.handle_asset_create(SimpleNamespace(asset_type="bad")))
        print_mock.assert_called_once()

        with patch.object(asset_commands, "delete_asset", return_value={"ok": True}) as delete_asset:
            result = asset_commands.handle_asset_delete(SimpleNamespace(name="x"))
        self.assertEqual(result, {"ok": True})
        delete_asset.assert_called_once()

    def test_event_wrappers_forward_arguments(self):
        with patch.object(event_commands, "add_event", return_value=True) as add_event:
            self.assertTrue(event_commands.handle_event_add(SimpleNamespace(object="o_player", event="create", template=None)))
        add_event.assert_called_once_with("o_player", "create", "")

        with patch.object(event_commands, "remove_event", return_value=True) as remove_event:
            self.assertTrue(event_commands.handle_event_remove(SimpleNamespace(object="o_player", event="destroy", keep_file=True)))
        remove_event.assert_called_once_with("o_player", "destroy", True)

        with patch.object(event_commands, "duplicate_event", return_value=True) as duplicate_event:
            self.assertTrue(event_commands.handle_event_duplicate(SimpleNamespace(object="o_player", source_event="create", target_num=1)))
        duplicate_event.assert_called_once_with("o_player", "create", 1)

        with patch.object(event_commands, "list_events", return_value=["create"]) as list_events:
            self.assertEqual(event_commands.handle_event_list(SimpleNamespace(object="o_player")), ["create"])
        list_events.assert_called_once_with("o_player")

        with patch.object(
            event_commands,
            "sync_object_events",
            side_effect=[
                {"orphaned_found": 0, "missing_found": 0},
                {"orphaned_found": 1, "missing_found": 0},
                {"orphaned_found": 2, "missing_found": 3},
            ],
        ) as sync_object_events:
            self.assertTrue(event_commands.handle_event_validate(SimpleNamespace(object="o_good")))
            self.assertFalse(event_commands.handle_event_validate(SimpleNamespace(object="o_bad")))
            self.assertTrue(event_commands.handle_event_fix(SimpleNamespace(object="o_fix")))
        self.assertEqual(sync_object_events.call_count, 3)

    def test_maintenance_wrappers_and_health(self):
        result_obj = SimpleNamespace(has_errors=False)
        with patch.object(maintenance_commands, "run_auto_maintenance", return_value=result_obj) as run_auto:
            self.assertTrue(
                maintenance_commands.handle_maintenance_auto(
                    SimpleNamespace(project_root="/tmp/project", fix=True, verbose=False)
                )
            )
        run_auto.assert_called_once_with(project_root="/tmp/project", fix_issues=True, verbose=False)

        passthroughs = {
            "maint_lint_command": "handle_maintenance_lint",
            "maint_validate_json_command": "handle_maintenance_validate_json",
            "maint_list_orphans_command": "handle_maintenance_list_orphans",
            "maint_prune_missing_command": "handle_maintenance_prune_missing",
            "maint_validate_paths_command": "handle_maintenance_validate_paths",
            "maint_dedupe_resources_command": "handle_maintenance_dedupe_resources",
            "maint_sync_events_command": "handle_maintenance_sync_events",
            "maint_clean_old_files_command": "handle_maintenance_clean_old_files",
            "maint_clean_orphans_command": "handle_maintenance_clean_orphans",
            "maint_fix_issues_command": "handle_maintenance_fix_issues",
        }
        for name, wrapper in passthroughs.items():
            with self.subTest(name=name), patch.object(maintenance_commands, name, return_value=True) as handler:
                self.assertTrue(getattr(maintenance_commands, wrapper)(SimpleNamespace()))
                handler.assert_called_once()

        health_result = SimpleNamespace(details=["ok one", "ok two"], success=True)
        with patch.object(maintenance_commands, "gm_mcp_health", return_value=health_result), patch("builtins.print") as print_mock:
            self.assertTrue(maintenance_commands.handle_maintenance_health(SimpleNamespace(project_root="/tmp/project")))
        self.assertEqual(print_mock.call_count, 2)

    def test_room_wrappers_normalize_and_forward(self):
        with patch.object(room_commands, "add_layer", return_value=True) as add_layer:
            self.assertTrue(
                room_commands.handle_room_layer_add(
                    SimpleNamespace(room_name="r_main", layer_name="Actors", layer_type="instances", depth=42)
                )
            )
        add_layer.assert_called_once_with("r_main", "Actors", "instance", 42)

        with patch.object(room_commands, "remove_layer", return_value=True) as remove_layer:
            self.assertTrue(room_commands.handle_room_layer_remove(SimpleNamespace(room_name="r_main", layer_name="Actors")))
        remove_layer.assert_called_once_with("r_main", "Actors")

        with patch.object(room_commands, "list_layers", return_value=["Actors"]) as list_layers:
            self.assertEqual(room_commands.handle_room_layer_list(SimpleNamespace(room_name="r_main")), ["Actors"])
        list_layers.assert_called_once_with("r_main")

        with patch.object(room_commands, "duplicate_room", return_value=True) as duplicate_room:
            self.assertTrue(room_commands.handle_room_duplicate(SimpleNamespace(source_room="r_old", new_name="r_new")))
        duplicate_room.assert_called_once_with("r_old", "r_new")

        with patch.object(room_commands, "rename_room", return_value=True) as rename_room:
            self.assertTrue(room_commands.handle_room_rename(SimpleNamespace(room_name="r_old", new_name="r_new")))
        rename_room.assert_called_once_with("r_old", "r_new")

        with patch.object(room_commands, "delete_room", return_value=True) as delete_room:
            self.assertTrue(room_commands.handle_room_delete(SimpleNamespace(room_name="r_old", dry_run=True)))
        delete_room.assert_called_once_with("r_old", True)

        with patch.object(room_commands, "list_rooms", return_value=["r_old"]) as list_rooms:
            self.assertEqual(room_commands.handle_room_list(SimpleNamespace(verbose=True)), ["r_old"])
        list_rooms.assert_called_once_with(True)

        with patch.object(room_commands, "add_instance", return_value=True) as add_instance:
            self.assertTrue(
                room_commands.handle_room_instance_add(
                    SimpleNamespace(room_name="r_main", object_name="o_player", x=10, y=20, layer=None)
                )
            )
        add_instance.assert_called_once_with("r_main", "o_player", 10, 20, "Instances")

        with patch.object(room_commands, "remove_instance", return_value=True) as remove_instance:
            self.assertTrue(room_commands.handle_room_instance_remove(SimpleNamespace(room_name="r_main", instance_id="inst_1")))
        remove_instance.assert_called_once_with("r_main", "inst_1")

        with patch.object(room_commands, "list_instances", return_value=["inst_1"]) as list_instances:
            self.assertEqual(
                room_commands.handle_room_instance_list(SimpleNamespace(room_name="r_main", layer="Actors")),
                ["inst_1"],
            )
        list_instances.assert_called_once_with("r_main", "Actors")

    def test_workflow_wrappers_and_safe_delete_paths(self):
        with patch.object(workflow_commands, "duplicate_asset", return_value={"ok": True}) as duplicate_asset:
            result = workflow_commands.handle_workflow_duplicate(
                SimpleNamespace(project_root=".", asset_path="scripts/scr_old/scr_old.yy", new_name="scr_new", yes=True)
            )
        self.assertEqual(result, {"ok": True})
        duplicate_asset.assert_called_once()

        with patch.object(workflow_commands, "rename_asset", return_value={"ok": True}) as rename_asset:
            workflow_commands.handle_workflow_rename(
                SimpleNamespace(project_root=".", asset_path="scripts/scr_old/scr_old.yy", new_name="scr_new")
            )
        rename_asset.assert_called_once()

        with patch.object(workflow_commands, "delete_asset", return_value={"ok": True}) as delete_asset:
            workflow_commands.handle_workflow_delete(
                SimpleNamespace(project_root=".", asset_path="scripts/scr_old/scr_old.yy", dry_run=True)
            )
        delete_asset.assert_called_once()

        with patch.object(workflow_commands, "swap_sprite_png", return_value={"ok": True}) as swap_sprite_png:
            workflow_commands.handle_workflow_swap_sprite(
                SimpleNamespace(project_root=".", asset_path="sprites/spr.yy", png="/tmp/image.png", frame=2)
            )
        swap_sprite_png.assert_called_once()

        scenarios = [
            ({"ok": False, "error": "blocked"}, False),
            ({"ok": True, "blocked": True, "dependencies": [{"asset_type": "script", "asset_name": "scr_test", "relation": "ref"}]}, False),
            ({"ok": True, "dry_run": True}, True),
            ({"ok": True, "deleted": True}, True),
        ]
        for result_obj, expected in scenarios:
            with self.subTest(result=result_obj), patch.object(
                workflow_commands, "safe_delete_asset", return_value=result_obj
            ), patch("builtins.print"):
                result = workflow_commands.handle_workflow_safe_delete(
                    SimpleNamespace(project_root=".", asset_type="script", asset_name="scr_test", force=False, clean_refs=False, apply=False)
                )
            self.assertEqual(result, expected)

    def test_runner_wrappers_cover_success_failure_and_exceptions(self):
        compile_args = SimpleNamespace(project_root="/tmp/project", runtime_version="1.0.0", platform=None, runtime="YYC")
        runner_instance = Mock()
        runner_instance.compile_project.return_value = True
        with patch.object(runner_commands, "GameMakerRunner", return_value=runner_instance) as runner_cls, patch.object(
            runner_commands, "detect_default_target_platform", return_value="Linux"
        ):
            result, stdout, _ = _capture_output(runner_commands.handle_runner_compile, compile_args)
        self.assertTrue(result)
        self.assertIn("Compilation completed successfully", stdout)
        runner_cls.assert_called_once_with(Path("/tmp/project").resolve(), runtime_version="1.0.0")
        runner_instance.compile_project.assert_called_once_with("Linux", "YYC")

        runner_instance = Mock(last_failure_message="bad build")
        runner_instance.compile_project.return_value = False
        with patch.object(runner_commands, "GameMakerRunner", return_value=runner_instance), patch.object(
            runner_commands, "detect_default_target_platform", return_value="Windows"
        ):
            result, stdout, _ = _capture_output(runner_commands.handle_runner_compile, SimpleNamespace(project_root=None, runtime="VM"))
        self.assertFalse(result)
        self.assertIn("bad build", stdout)

        with patch.object(runner_commands, "GameMakerRunner", side_effect=RuntimeError("compile boom")):
            result, stdout, _ = _capture_output(runner_commands.handle_runner_compile, SimpleNamespace(project_root=".", runtime="VM"))
        self.assertFalse(result)
        self.assertIn("Error during compilation: compile boom", stdout)

        run_instance = Mock()
        run_instance.run_project_direct.return_value = {"ok": True, "pid": 1}
        with patch.object(runner_commands, "GameMakerRunner", return_value=run_instance), patch.object(
            runner_commands, "detect_default_target_platform", return_value="macOS"
        ):
            result, stdout, _ = _capture_output(
                runner_commands.handle_runner_run,
                SimpleNamespace(project_root="/tmp/project", runtime_version=None, platform=None, runtime="VM", background=True, output_location="project"),
            )
        self.assertEqual(result["pid"], 1)
        self.assertIn("Running GameMaker project", stdout)

        with patch.object(runner_commands, "GameMakerRunner", side_effect=RuntimeError("run boom")):
            result, _, _ = _capture_output(
                runner_commands.handle_runner_run,
                SimpleNamespace(project_root=".", background=False),
            )
        self.assertFalse(result)

        with patch.object(runner_commands, "GameMakerRunner", side_effect=RuntimeError("run boom")):
            result, _, _ = _capture_output(
                runner_commands.handle_runner_run,
                SimpleNamespace(project_root=".", background=True),
            )
        self.assertFalse(result["ok"])
        self.assertIn("Failed to start game", result["message"])

        stop_instance = Mock()
        stop_instance.stop_game.return_value = {"ok": True, "message": "stopped"}
        with patch.object(runner_commands, "GameMakerRunner", return_value=stop_instance):
            result, stdout, _ = _capture_output(runner_commands.handle_runner_stop, SimpleNamespace(project_root="/tmp/project"))
        self.assertTrue(result["ok"])
        self.assertIn("[OK] stopped", stdout)

        stop_instance.stop_game.return_value = {"ok": False, "message": "not running"}
        with patch.object(runner_commands, "GameMakerRunner", return_value=stop_instance):
            result, stdout, _ = _capture_output(runner_commands.handle_runner_stop, SimpleNamespace(project_root="/tmp/project"))
        self.assertFalse(result["ok"])
        self.assertIn("[WARN] not running", stdout)

        with patch.object(runner_commands, "GameMakerRunner", side_effect=RuntimeError("stop boom")):
            result, _, _ = _capture_output(runner_commands.handle_runner_stop, SimpleNamespace(project_root="."))
        self.assertFalse(result["ok"])

        status_instance = Mock()
        status_instance.get_game_status.return_value = {
            "ok": True,
            "running": True,
            "message": "running",
            "pid": 123,
            "run_id": "run-1",
            "started_at": "2026-03-10T10:00:00",
        }
        with patch.object(runner_commands, "GameMakerRunner", return_value=status_instance):
            result, stdout, _ = _capture_output(runner_commands.handle_runner_status, SimpleNamespace(project_root="/tmp/project"))
        self.assertTrue(result["running"])
        self.assertIn("PID: 123", stdout)

        with patch.object(runner_commands, "GameMakerRunner", side_effect=RuntimeError("status boom")):
            result, stdout, _ = _capture_output(runner_commands.handle_runner_status, SimpleNamespace(project_root="."))
        self.assertFalse(result["ok"])
        self.assertIn("Error checking status: status boom", stdout)


class TestServerHelpers(unittest.TestCase):
    def test_platform_output_and_project_helpers(self):
        with patch("gms_mcp.server.platform.platform.system", return_value="Darwin"):
            self.assertEqual(server_platform._default_target_platform(), "macOS")
        with patch("gms_mcp.server.platform.platform.system", return_value="Linux"):
            self.assertEqual(server_platform._default_target_platform(), "Linux")
        with patch("gms_mcp.server.platform.platform.system", return_value="Windows"):
            self.assertEqual(server_platform._default_target_platform(), "Windows")

        result = server_output._apply_output_mode({"stdout": "a\nb\nc", "stderr": "x\ny"}, output_mode="full")
        self.assertEqual(result["stdout"], "a\nb\nc")

        result = server_output._apply_output_mode({"stdout": "a\nb\nc", "stderr": "x\ny"}, output_mode="none")
        self.assertEqual(result["stdout"], "")
        self.assertTrue(result["stdout_truncated"])

        result = server_output._apply_output_mode(
            {"stdout": "1\n2\n3\n4", "stderr": "e1\ne2"},
            output_mode="tail",
            tail_lines=2,
            max_chars=3,
        )
        self.assertEqual(result["stdout"], "3\n4")
        self.assertTrue(result["stderr_truncated"])

        result = server_output._apply_output_mode(
            {"stdout": "1\n2\n3", "stderr": ""},
            output_mode="full",
            quiet=True,
            tail_lines=1,
        )
        self.assertEqual(result["stdout"], "3")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "game.yyp").write_text("{}", encoding="utf-8")
            nested = root / "sub" / "folder"
            nested.mkdir(parents=True)
            gm_root = root / "gmrepo"
            gm_project = gm_root / "gamemaker"
            gm_project.mkdir(parents=True)
            (gm_project / "nested_game.yyp").write_text("{}", encoding="utf-8")

            self.assertEqual(server_project._list_yyp_files(root), [root / "game.yyp"])
            self.assertEqual(server_project._search_upwards_for_yyp(nested), root.resolve())
            self.assertEqual(server_project._search_upwards_for_gamemaker_yyp(gm_project), gm_project.resolve())
            self.assertEqual(server_project._resolve_project_directory_no_deps(str(root)), root)
            self.assertEqual(server_project._resolve_project_directory_no_deps(str(gm_root)), gm_project)
            self.assertEqual(server_project._resolve_repo_root(str(root)), root.resolve())
            self.assertEqual(server_project._find_yyp_file(root), "game.yyp")
            self.assertIsNone(server_project._find_yyp_file(root / "missing"))
            self.assertEqual(server_project._list_yyp_files(Path("/definitely/missing")), [])
            self.assertIsNone(server_project._resolve_project_directory("nope") if False else None)

            file_path = root / "game.yyp"
            self.assertEqual(server_project._resolve_project_directory_no_deps(str(file_path)), root)

            with patch.dict(os.environ, {"GM_PROJECT_ROOT": str(root)}, clear=False):
                self.assertEqual(server_project._resolve_project_directory_no_deps(None), root)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {}, clear=True), patch("gms_mcp.project_detection.Path.cwd", return_value=Path(temp_dir)):
                with self.assertRaises(FileNotFoundError):
                    server_project._resolve_project_directory_no_deps(None)

        self.assertIsNone(server_project._ensure_cli_on_sys_path(Path(".")))

    def test_resources_register_and_return_json(self):
        mcp = FakeMCP()
        server_resources.register(mcp)

        with patch("gms_mcp.server.resources._resolve_project_directory", return_value=Path("/tmp/project")), patch(
            "gms_helpers.introspection.build_project_index",
            return_value={"assets": ["a"]},
        ):
            result = asyncio.run(mcp.resources["gms://project/index"]())
        self.assertIn('"assets"', result)

        with patch("gms_mcp.server.resources._resolve_project_directory", return_value=Path("/tmp/project")), patch(
            "gms_helpers.introspection.build_asset_graph",
            return_value={"nodes": [], "edges": []},
        ):
            result = asyncio.run(mcp.resources["gms://project/asset-graph"]())
        self.assertIn('"nodes"', result)

        with patch("gms_mcp.server.resources.get_update_status", return_value=SimpleNamespace(message="Up to date")):
            result = asyncio.run(mcp.resources["gms://system/updates"]())
        self.assertEqual(result, "Up to date")


class TestRuntimeTools(MCPToolTestCase):
    module = runtime_tools

    def test_runtime_wrappers(self):
        installed = [SimpleNamespace(to_dict=lambda: {"version": "1"}), SimpleNamespace(to_dict=lambda: {"version": "2"})]
        manager = Mock()
        manager.list_installed.return_value = installed
        manager.get_pinned.return_value = "1"
        manager.select.return_value = SimpleNamespace(version="2")
        manager.pin.return_value = True
        manager.unpin.return_value = False
        manager.verify.return_value = {"ok": True}

        with patch("gms_mcp.server.tools.runtime._resolve_project_directory_no_deps", return_value=Path("/tmp/project")), patch(
            "gms_helpers.runtime_manager.RuntimeManager", return_value=manager
        ):
            listed = self.call_tool("gm_runtime_list", project_root="/tmp/project")
            pinned = self.call_tool("gm_runtime_pin", version="2", project_root="/tmp/project")
            unpinned = self.call_tool("gm_runtime_unpin", project_root="/tmp/project")
            verified = self.call_tool("gm_runtime_verify", version="2", project_root="/tmp/project")

        self.assertEqual(listed["count"], 2)
        self.assertTrue(pinned["ok"])
        self.assertEqual(unpinned["message"], "No runtime pin existed.")
        self.assertTrue(verified["ok"])


class TestDocsTools(MCPToolTestCase):
    module = docs_tools

    def test_docs_wrappers(self):
        with patch("gms_helpers.gml_docs.lookup", return_value={"ok": True}), patch(
            "gms_helpers.gml_docs.search", return_value={"ok": True, "results": []}
        ), patch(
            "gms_helpers.gml_docs.list_functions", return_value={"ok": True, "results": []}
        ), patch(
            "gms_helpers.gml_docs.list_categories", return_value={"ok": True}
        ), patch(
            "gms_helpers.gml_docs.get_cache_stats", return_value={"ok": True}
        ), patch(
            "gms_helpers.gml_docs.clear_cache", return_value={"ok": True}
        ):
            self.assertTrue(self.call_tool("gm_doc_lookup", function_name="draw_sprite")["ok"])
            self.assertTrue(self.call_tool("gm_doc_search", query="draw")["ok"])
            self.assertTrue(self.call_tool("gm_doc_list")["ok"])
            self.assertTrue(self.call_tool("gm_doc_categories")["ok"])
            self.assertTrue(self.call_tool("gm_doc_cache_stats")["ok"])
            self.assertTrue(self.call_tool("gm_doc_cache_clear")["ok"])


class TestIntrospectionTools(MCPToolTestCase):
    module = introspection_tools

    def test_introspection_wrappers(self):
        with patch("gms_mcp.server.tools.introspection._resolve_project_directory", return_value=Path("/tmp/project")), patch(
            "gms_helpers.introspection.list_assets_by_type", return_value={"script": [{"name": "scr_test"}]}
        ), patch(
            "gms_helpers.introspection.read_asset_yy", side_effect=[{"name": "scr_test"}, None]
        ), patch(
            "gms_helpers.introspection.search_references", return_value=[{"path": "scripts/scr.gml"}]
        ), patch(
            "gms_helpers.introspection.build_asset_graph", return_value={"nodes": []}
        ), patch(
            "gms_helpers.introspection.get_project_stats", return_value={"objects": 1}
        ):
            listed = self.call_tool("gm_list_assets", project_root="/tmp/project", asset_type="script")
            found = self.call_tool("gm_read_asset", project_root="/tmp/project", asset_identifier="scr_test")
            missing = self.call_tool("gm_read_asset", project_root="/tmp/project", asset_identifier="missing")
            refs = self.call_tool("gm_search_references", project_root="/tmp/project", pattern="player")
            graph = self.call_tool("gm_get_asset_graph", project_root="/tmp/project", deep=True)
            stats = self.call_tool("gm_get_project_stats", project_root="/tmp/project")

        self.assertEqual(listed["count"], 1)
        self.assertTrue(found["ok"])
        self.assertFalse(missing["ok"])
        self.assertEqual(refs["count"], 1)
        self.assertEqual(graph["nodes"], [])
        self.assertEqual(stats["objects"], 1)


class TestEventTools(MCPToolTestCase):
    module = event_tools

    def test_event_wrappers_build_expected_cli_args(self):
        with patch(
            "gms_mcp.server.tools.events._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as fallback, patch("gms_mcp.server.tools.events._resolve_repo_root", return_value=Path("/tmp/project")), patch(
            "gms_mcp.server.tools.events._ensure_cli_on_sys_path"
        ):
            cases = [
                ("gm_event_add", {"object": "o_player", "event": "create", "template": "basic", "project_root": "/tmp/project"}, ["event", "add", "o_player", "create", "--template", "basic"]),
                ("gm_event_remove", {"object": "o_player", "event": "destroy", "keep_file": True, "project_root": "/tmp/project"}, ["event", "remove", "o_player", "destroy", "--keep-file"]),
                ("gm_event_duplicate", {"object": "o_player", "source_event": "create", "target_num": 2, "project_root": "/tmp/project"}, ["event", "duplicate", "o_player", "create", "2"]),
                ("gm_event_list", {"object": "o_player", "project_root": "/tmp/project"}, ["event", "list", "o_player"]),
                ("gm_event_validate", {"object": "o_player", "project_root": "/tmp/project"}, ["event", "validate", "o_player"]),
                ("gm_event_fix", {"object": "o_player", "safe_mode": False, "project_root": "/tmp/project"}, ["event", "fix", "o_player", "--no-safe-mode"]),
            ]
            for tool_name, kwargs, cli_args in cases:
                with self.subTest(tool_name=tool_name):
                    result = self.call_tool(tool_name, **kwargs)
                    self.assertTrue(result["ok"])
                    self.assertEqual(fallback.await_args_list[-1].kwargs["cli_args"], cli_args)


class TestCodeIntelTools(MCPToolTestCase):
    module = code_intel

    def test_code_intel_wrappers_build_expected_cli_args(self):
        with patch(
            "gms_mcp.server.tools.code_intel._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as fallback, patch("gms_mcp.server.tools.code_intel._resolve_repo_root", return_value=Path("/tmp/project")), patch(
            "gms_mcp.server.tools.code_intel._resolve_project_directory", return_value=Path("/tmp/project")
        ), patch("gms_mcp.server.tools.code_intel._ensure_cli_on_sys_path"):
            cases = [
                ("gm_build_index", {"project_root": "/tmp/project", "force": True}, ["symbol", "build", "--force"]),
                ("gm_find_definition", {"project_root": "/tmp/project", "symbol_name": "player_move"}, ["symbol", "find-definition", "player_move"]),
                ("gm_find_references", {"project_root": "/tmp/project", "symbol_name": "player_move", "max_results": 25}, ["symbol", "find-references", "player_move", "--max", "25"]),
                ("gm_list_symbols", {"project_root": "/tmp/project", "kind": "function", "name_filter": "player", "file_filter": "scripts", "max_results": 10}, ["symbol", "list", "--kind", "function", "--name", "player", "--file", "scripts", "--max", "10"]),
            ]
            for tool_name, kwargs, cli_args in cases:
                with self.subTest(tool_name=tool_name):
                    result = self.call_tool(tool_name, **kwargs)
                    self.assertTrue(result["ok"])
                    self.assertEqual(fallback.await_args_list[-1].kwargs["cli_args"], cli_args)


class TestProjectHealthTools(MCPToolTestCase):
    module = project_health

    def test_project_health_wrappers(self):
        with patch("gms_mcp.server.tools.project_health._resolve_project_directory_no_deps", return_value=Path("/tmp/project")), patch(
            "gms_mcp.server.tools.project_health._find_yyp_file", return_value="game.yyp"
        ), patch(
            "gms_mcp.server.tools.project_health.get_update_status",
            return_value=SimpleNamespace(to_dict=lambda: {"status": "ok", "message": "Up to date"}),
        ):
            info = self.call_tool("gm_project_info", project_root="/tmp/project")
        self.assertEqual(info["yyp"], "game.yyp")
        self.assertEqual(info["updates"]["status"], "ok")

        with patch(
            "gms_helpers.health.gm_mcp_health",
            return_value=SimpleNamespace(
                to_dict=lambda: {
                    "success": True,
                    "message": "Health check passed!",
                    "issues_found": 0,
                    "issues_fixed": 0,
                    "details": [],
                    "data": {"checks": []},
                }
            ),
        ):
            health = self.call_tool("gm_mcp_health", project_root="/tmp/project")
        self.assertTrue(health["ok"])
        self.assertIn("data", health)

        async_result = SimpleNamespace(as_dict=lambda: {"ok": True, "stdout": "a\nb\nc", "stderr": ""})
        with patch(
            "gms_mcp.server.tools.project_health._run_cli_async",
            new=AsyncMock(return_value=async_result),
        ):
            result = self.call_tool("gm_cli", args=["maintenance", "auto"], project_root="/tmp/project", prefer_cli=True)
        self.assertTrue(result["ok"])

        with patch(
            "gms_mcp.server.tools.project_health._run_gms_inprocess",
            return_value=SimpleNamespace(as_dict=lambda: {"ok": True, "stdout": "good", "stderr": ""}),
        ):
            result = self.call_tool("gm_cli", args=["maintenance", "auto"], project_root="/tmp/project", prefer_cli=False)
        self.assertTrue(result["ok"])

        with patch(
            "gms_mcp.server.tools.project_health._run_gms_inprocess",
            return_value=SimpleNamespace(as_dict=lambda: {"ok": False, "error": "direct failed", "stdout": "", "stderr": ""}),
        ):
            result = self.call_tool(
                "gm_cli",
                args=["maintenance", "auto"],
                project_root="/tmp/project",
                prefer_cli=False,
                fallback_to_subprocess=False,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "direct failed")

        async_result = SimpleNamespace(as_dict=lambda: {"ok": True, "stdout": "cli", "stderr": ""})
        with patch(
            "gms_mcp.server.tools.project_health._run_gms_inprocess",
            return_value=SimpleNamespace(as_dict=lambda: {"ok": False, "error": "direct failed", "stdout": "", "stderr": ""}),
        ), patch(
            "gms_mcp.server.tools.project_health._run_cli_async",
            new=AsyncMock(return_value=async_result),
        ):
            result = self.call_tool(
                "gm_cli",
                args=["maintenance", "auto"],
                project_root="/tmp/project",
                prefer_cli=False,
            )
        self.assertEqual(result["direct_error"], "direct failed")

        with patch(
            "gms_mcp.server.tools.project_health._run_with_fallback",
            new=AsyncMock(return_value={"ok": True}),
        ) as fallback, patch("gms_mcp.server.tools.project_health._resolve_repo_root", return_value=Path("/tmp/project")), patch(
            "gms_mcp.server.tools.project_health._ensure_cli_on_sys_path"
        ):
            diagnostics = self.call_tool("gm_diagnostics", depth="deep", include_info=True, project_root="/tmp/project")
        self.assertTrue(diagnostics["ok"])
        self.assertEqual(fallback.await_args.kwargs["cli_args"], ["diagnostics", "--depth", "deep", "--include-info"])

        with patch(
            "gms_mcp.server.tools.project_health.get_update_status",
            return_value=SimpleNamespace(to_dict=lambda: {"status": "warn", "message": "new version"}),
        ):
            updates = self.call_tool("gm_check_updates")
        self.assertEqual(updates["message"], "new version")
        self.assertEqual(updates["status"], "warn")


if __name__ == "__main__":
    unittest.main()
