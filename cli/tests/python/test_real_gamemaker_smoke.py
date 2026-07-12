import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.run_real_gamemaker_smoke as real_smoke


def _write_minimal_project(project_root: Path, *, ide_version: str = "2026.0.0.23") -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "SmokeProject.yyp").write_text(
        json.dumps(
            {
                "name": "SmokeProject",
                "resources": [],
                "MetaData": {"IDEVersion": ide_version},
            }
        ),
        encoding="utf-8",
    )


class _FakeServer:
    async def call_tool(self, tool_name, arguments):
        if tool_name == "gm_create_sprite":
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "smart"
            return {
                "ok": True,
                "transaction": {
                    "verification_policy": {"mode": "smart", "action": "compile"},
                    "compile_verification": {"ok": True},
                },
            }
        if tool_name == "gm_sprite_add_frame":
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "smart"
            return {
                "ok": True,
                "transaction": {
                    "verification_policy": {"mode": "smart", "action": "defer"},
                    "pending_compile_verification": {"required": True, "operation_count": 1},
                },
            }
        if tool_name in {"gm_create_object", "gm_create_room"}:
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "off"
            project_root = Path(arguments["project_root"])
            name = arguments["name"]
            directory = "objects" if tool_name == "gm_create_object" else "rooms"
            asset_dir = project_root / directory / name
            asset_dir.mkdir(parents=True, exist_ok=True)
            payload = (
                {
                    "$GMObject": "",
                    "%Name": name,
                    "name": name,
                    "eventList": [],
                    "resourceType": "GMObject",
                }
                if tool_name == "gm_create_object"
                else {"$GMRoom": "", "%Name": name, "name": name, "resourceType": "GMRoom"}
            )
            (asset_dir / f"{name}.yy").write_text(json.dumps(payload), encoding="utf-8")
            yyp_path = next(project_root.glob("*.yyp"))
            project = json.loads(yyp_path.read_text(encoding="utf-8"))
            path = f"{directory}/{name}/{name}.yy"
            project.setdefault("resources", []).append({"id": {"name": name, "path": path}})
            if directory == "rooms":
                project.setdefault("RoomOrderNodes", []).append({"roomId": {"name": name, "path": path}})
            yyp_path.write_text(json.dumps(project), encoding="utf-8")
            return {"ok": True, "transaction": {"verification_policy": {"action": "skip"}}}
        if tool_name == "gm_event_add":
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "smart"
            project_root = Path(arguments["project_root"])
            object_dir = project_root / "objects" / arguments["object"]
            object_dir.mkdir(parents=True, exist_ok=True)
            object_path = object_dir / f"{arguments['object']}.yy"
            object_data = json.loads(object_path.read_text(encoding="utf-8"))
            object_data["eventList"] = [
                {
                    "$GMEvent": "v1",
                    "%Name": "Collision_o_real_smoke_collision_target",
                    "name": "Collision_o_real_smoke_collision_target",
                    "eventType": 4,
                    "eventNum": 0,
                    "collisionObjectId": {
                        "name": "o_real_smoke_collision_target",
                        "path": "objects/o_real_smoke_collision_target/o_real_smoke_collision_target.yy",
                    },
                }
            ]
            object_path.write_text(json.dumps(object_data), encoding="utf-8")
            (object_dir / "Collision_o_real_smoke_collision_target.gml").write_text("// collision\n")
            return {
                "ok": True,
                "transaction": {"verification_policy": {"mode": "smart", "action": "defer"}},
            }
        if tool_name == "gm_workflow_duplicate":
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "off"
            project_root = Path(arguments["project_root"])
            source_name = "r_real_smoke_order_source"
            new_name = arguments["new_name"]
            source_dir = project_root / "rooms" / source_name
            destination = project_root / "rooms" / new_name
            shutil.copytree(source_dir, destination)
            (destination / f"{source_name}.yy").rename(destination / f"{new_name}.yy")
            room = json.loads((destination / f"{new_name}.yy").read_text(encoding="utf-8"))
            room["name"] = room["%Name"] = new_name
            (destination / f"{new_name}.yy").write_text(json.dumps(room), encoding="utf-8")
            yyp_path = next(project_root.glob("*.yyp"))
            project = json.loads(yyp_path.read_text(encoding="utf-8"))
            new_path = f"rooms/{new_name}/{new_name}.yy"
            project["resources"].append({"id": {"name": new_name, "path": new_path}})
            project["RoomOrderNodes"].append({"roomId": {"name": new_name, "path": new_path}})
            yyp_path.write_text(json.dumps(project), encoding="utf-8")
            return {"ok": True, "transaction": {"verification_policy": {"action": "skip"}}}
        if tool_name == "gm_safe_delete":
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "off"
            project_root = Path(arguments["project_root"])
            name = arguments["asset_name"]
            shutil.rmtree(project_root / "rooms" / name)
            yyp_path = next(project_root.glob("*.yyp"))
            project = json.loads(yyp_path.read_text(encoding="utf-8"))
            project["resources"] = [entry for entry in project["resources"] if entry["id"]["name"] != name]
            project["RoomOrderNodes"] = [
                entry for entry in project["RoomOrderNodes"] if entry["roomId"]["name"] != name
            ]
            yyp_path.write_text(json.dumps(project), encoding="utf-8")
            return {"ok": True, "transaction": {"verification_policy": {"action": "skip"}}}
        if tool_name == "gm_workflow_rename":
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "smart"
            project_root = Path(arguments["project_root"])
            old_name = "o_real_smoke_collision_target"
            new_name = arguments["new_name"]
            old_dir = project_root / "objects" / old_name
            new_dir = project_root / "objects" / new_name
            old_dir.rename(new_dir)
            (new_dir / f"{old_name}.yy").rename(new_dir / f"{new_name}.yy")
            target = json.loads((new_dir / f"{new_name}.yy").read_text(encoding="utf-8"))
            target["name"] = target["%Name"] = new_name
            (new_dir / f"{new_name}.yy").write_text(json.dumps(target), encoding="utf-8")
            source_path = project_root / "objects/o_real_smoke_collision_source/o_real_smoke_collision_source.yy"
            source = json.loads(source_path.read_text(encoding="utf-8"))
            event = source["eventList"][0]
            event["%Name"] = event["name"] = f"Collision_{new_name}"
            event["collisionObjectId"] = {
                "name": new_name,
                "path": f"objects/{new_name}/{new_name}.yy",
            }
            source_path.write_text(json.dumps(source), encoding="utf-8")
            old_collision = source_path.parent / f"Collision_{old_name}.gml"
            old_collision.rename(source_path.parent / f"Collision_{new_name}.gml")
            return {
                "ok": True,
                "transaction": {
                    "verification_policy": {"mode": "smart", "action": "compile"},
                    "compile_verification": {"ok": True},
                },
            }
        if tool_name == "gm_verification_flush":
            assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "smart"
            return {
                "ok": True,
                "compiled": True,
                "compile_verification": {"ok": True},
                "pending_compile_verification": None,
            }
        return {"ok": False, "error": f"unexpected tool {tool_name}"}


class TestRealGameMakerSmoke(unittest.TestCase):
    def test_main_skips_without_configured_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "smoke.json"
            argv = ["run_real_gamemaker_smoke.py", "--output", str(output)]

            with (
                patch.object(sys, "argv", argv),
                patch.object(real_smoke, "_find_default_project", return_value=None),
            ):
                exit_code = real_smoke.main()

            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "skipped")

    def test_main_fails_required_gate_without_configured_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "smoke.json"
            argv = ["run_real_gamemaker_smoke.py", "--output", str(output), "--required"]

            with (
                patch.object(sys, "argv", argv),
                patch.object(real_smoke, "_find_default_project", return_value=None),
            ):
                exit_code = real_smoke.main()

            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "failed")

    def test_main_runs_smart_verification_sequence_against_project_copy(self):
        runtime = SimpleNamespace(
            is_valid=True,
            version="runtime-test",
            channel="stable",
            path="/tmp/runtime",
            igor_path="/tmp/runtime/bin/Igor",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_project = temp_path / "source"
            work_root = temp_path / "work"
            output = temp_path / "smoke.json"
            _write_minimal_project(source_project)
            argv = [
                "run_real_gamemaker_smoke.py",
                "--project-root",
                str(source_project),
                "--work-root",
                str(work_root),
                "--output",
                str(output),
                "--fixture-name",
                "gm-2026-lts",
                "--expected-runtime-version",
                "runtime-*",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(real_smoke.RuntimeManager, "select", return_value=runtime),
                patch.object(real_smoke, "build_server", return_value=_FakeServer()),
            ):
                exit_code = real_smoke.main()

            report = json.loads(output.read_text(encoding="utf-8"))
            source_yyp = (source_project / "SmokeProject.yyp").resolve()
            expected_hash = hashlib.sha256(source_yyp.read_bytes()).hexdigest()

        self.assertEqual(exit_code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["fixture"]["name"], "gm-2026-lts")
        self.assertEqual(report["fixture"]["expected_runtime_version"], "runtime-*")
        self.assertEqual(report["fixture"]["source_yyp_name"], "SmokeProject.yyp")
        self.assertEqual(report["fixture"]["source_yyp_sha256"], expected_hash)
        self.assertEqual(report["fixture"]["source_ide_version"], "2026.0.0.23")
        serialized_report = json.dumps(report)
        self.assertNotIn(str(source_project), serialized_report)
        self.assertNotIn(str(work_root), serialized_report)
        self.assertNotIn("/tmp/runtime", serialized_report)
        self.assertNotIn("source_project", report)
        self.assertNotIn("work_project", report)
        self.assertNotIn("results", report)
        self.assertTrue(report["checks"]["high_risk_mutation_compiled"])
        self.assertTrue(report["checks"]["batchable_mutation_deferred"])
        self.assertTrue(report["checks"]["deferred_batch_flushed"])
        self.assertTrue(report["checks"]["collision_reference_emitted"])
        self.assertTrue(report["checks"]["collision_event_compiled"])

    def test_main_rejects_timeout_shorter_than_platform_cleanup_bound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_project = temp_path / "source"
            output = temp_path / "smoke.json"
            _write_minimal_project(source_project)
            argv = [
                "run_real_gamemaker_smoke.py",
                "--project-root",
                str(source_project),
                "--output",
                str(output),
                "--fixture-name",
                "gm-2024",
                "--expected-runtime-version",
                "2024.14.4.268",
                "--timeout-seconds",
                "30",
                "--required",
            ]
            runtime_report = {
                "ok": True,
                "version": "2024.14.4.268",
                "channel": "stable",
                "path": "/tmp/runtime",
                "igor_path": "/tmp/runtime/Igor",
            }

            with (
                patch.object(sys, "argv", argv),
                patch.object(real_smoke, "_runtime_report", return_value=runtime_report),
                patch.object(real_smoke, "build_server") as server_mock,
            ):
                exit_code = real_smoke.main()

            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertIn("at least 120 seconds", report["message"])
        server_mock.assert_not_called()

    def test_expected_runtime_version_mismatch_fails_required_fixture(self):
        runtime = SimpleNamespace(
            is_valid=True,
            version="2024.13.1",
            channel="stable",
            path="/tmp/runtime",
            igor_path="/tmp/runtime/bin/Igor",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_project = temp_path / "source"
            output = temp_path / "smoke.json"
            _write_minimal_project(source_project)
            argv = [
                "run_real_gamemaker_smoke.py",
                "--project-root",
                str(source_project),
                "--output",
                str(output),
                "--fixture-name",
                "gm-2026-lts",
                "--expected-runtime-version",
                "2026.*",
                "--required",
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(real_smoke.RuntimeManager, "list_installed", return_value=[]),
                patch.object(real_smoke.RuntimeManager, "select", return_value=runtime),
            ):
                exit_code = real_smoke.main()

            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["fixture"]["name"], "gm-2026-lts")
        self.assertEqual(report["runtime"]["version"], "2024.13.1")
        self.assertIn("does not match", report["message"])

    def test_runtime_version_match_is_exact_without_glob(self):
        self.assertTrue(real_smoke._runtime_version_matches("2024.14.4.268", "2024.14.4.268"))
        self.assertFalse(real_smoke._runtime_version_matches("2024.14.4.268999", "2024.14.4.268"))
        self.assertTrue(real_smoke._runtime_version_matches("2024.14.4.268", "2024.*"))


if __name__ == "__main__":
    unittest.main()
