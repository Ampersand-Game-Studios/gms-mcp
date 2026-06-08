import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.run_real_gamemaker_smoke as real_smoke


def _write_minimal_project(project_root: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "SmokeProject.yyp").write_text('{"name":"SmokeProject","resources":[]}', encoding="utf-8")


class _FakeServer:
    async def call_tool(self, tool_name, arguments):
        assert os.environ["GMS_MCP_POST_MUTATION_VERIFY"] == "smart"
        if tool_name == "gm_create_sprite":
            return {
                "ok": True,
                "transaction": {
                    "verification_policy": {"mode": "smart", "action": "compile"},
                    "compile_verification": {"ok": True},
                },
            }
        if tool_name == "gm_sprite_add_frame":
            return {
                "ok": True,
                "transaction": {
                    "verification_policy": {"mode": "smart", "action": "defer"},
                    "pending_compile_verification": {"required": True, "operation_count": 1},
                },
            }
        if tool_name == "gm_verification_flush":
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

        self.assertEqual(exit_code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["fixture"]["name"], "gm-2026-lts")
        self.assertEqual(report["fixture"]["expected_runtime_version"], "runtime-*")
        self.assertTrue(report["checks"]["high_risk_mutation_compiled"])
        self.assertTrue(report["checks"]["batchable_mutation_deferred"])
        self.assertTrue(report["checks"]["deferred_batch_flushed"])

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


if __name__ == "__main__":
    unittest.main()
