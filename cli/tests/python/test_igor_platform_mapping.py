#!/usr/bin/env python3
"""
Focused tests for Igor platform token mapping and prefab auto-detection.

These cover macOS-specific behavior without requiring Igor or a runtime install.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add source to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from gms_helpers.runner import GameMakerRunner, normalize_platform_target, _to_igor_platform


class TestIgorPlatformMapping(unittest.TestCase):
    def test_normalize_platform_target_macos_aliases(self):
        self.assertEqual(normalize_platform_target("macos"), "macOS")
        self.assertEqual(normalize_platform_target("osx"), "macOS")
        self.assertEqual(normalize_platform_target("mac"), "macOS")

    def test_to_igor_platform_mapping(self):
        self.assertEqual(_to_igor_platform("macOS"), "Mac")
        self.assertEqual(_to_igor_platform("Windows"), "Windows")
        self.assertEqual(_to_igor_platform("Linux"), "Linux")


class TestPrefabsAutoDetection(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.tmp_dir)
        (self.project_root / "test_project.yyp").write_text('{"name": "test_project", "resources": []}')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("gms_helpers.runner.platform.system", return_value="Darwin")
    def test_prefabs_path_prefers_users_shared_on_macos(self, _mock_system):
        runner = GameMakerRunner(self.project_root)

        shared_prefabs = "/Users/Shared/GameMakerStudio2/Prefabs"

        def fake_exists(path_obj: Path) -> bool:
            # `Path` is OS-specific; normalize so this test is stable on Windows CI.
            return path_obj.as_posix() == shared_prefabs

        with patch.dict(os.environ, {}, clear=True):
            # On Windows, clearing env vars can break Path.home() resolution.
            with patch("gms_helpers.runner.Path.home", return_value=Path("/fake/home")):
                with patch("gms_helpers.runner.Path.exists", autospec=True, side_effect=fake_exists):
                    found = runner.get_prefabs_path()

        self.assertIsNotNone(found)
        self.assertEqual(found.as_posix(), shared_prefabs)


class TestRunnerCommandSelection(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.tmp_dir)
        (self.project_root / "test_project.yyp").write_text('{"name": "test_project", "resources": []}')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _fake_find_runtime(self, runner: GameMakerRunner):
        runner.runtime_path = Path("/fake/runtime")
        return Path("/fake/Igor")

    def _fake_process(self):
        proc = MagicMock()
        proc.stdout = None
        proc.wait.return_value = 0
        proc.returncode = 0
        proc.pid = 12345
        return proc

    @patch.object(GameMakerRunner, "_wait_for_macos_main_loop", return_value=True)
    @patch.object(GameMakerRunner, "_stop_platform_process", return_value=True)
    def test_compile_project_uses_local_run_validation_on_macos(self, _mock_stop, _mock_wait):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []

        def fake_run_igor(cmd):
            captured_cmd[:] = cmd
            return self._fake_process()

        with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                        ok = runner.compile_project(platform_target="macOS", runtime_type="VM")

        self.assertTrue(ok)
        self.assertIn("Run", captured_cmd)
        self.assertNotIn("PackageZip", captured_cmd)
        self.assertNotIn("Tests", captured_cmd)
        self.assertFalse(any(str(arg).startswith("--tf=") for arg in captured_cmd))

    def test_compile_project_keeps_packagezip_on_windows(self):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []

        def fake_run_igor(cmd):
            captured_cmd[:] = cmd
            return self._fake_process()

        with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                        ok = runner.compile_project(platform_target="Windows", runtime_type="VM")

        self.assertTrue(ok)
        self.assertIn("PackageZip", captured_cmd)
        self.assertNotIn("Tests", captured_cmd)

    def test_macos_temp_run_uses_local_run_without_tf(self):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []

        def fake_run_igor(cmd):
            captured_cmd[:] = cmd
            return self._fake_process()

        with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                        with patch.object(runner, "_collect_igor_output_async", return_value=([], MagicMock())):
                            with patch.object(runner, "_wait_for_macos_runner_start", return_value=(222, {222}, {333})):
                                result = runner.run_project_direct(
                                    platform_target="macOS",
                                    runtime_type="VM",
                                    background=True,
                                    output_location="temp",
                                )

        self.assertTrue(result["ok"])
        self.assertTrue(result["background"])
        self.assertEqual(result["pid"], 222)
        self.assertIn("Run", captured_cmd)
        self.assertNotIn("PackageZip", captured_cmd)
        self.assertFalse(any(str(arg).startswith("--tf=") for arg in captured_cmd))

    def test_package_export_failure_message_mentions_signing_stage(self):
        runner = GameMakerRunner(self.project_root)
        message = runner._build_stage_failure_message(
            "package/export",
            1,
            ["Could not find matching certificate for Developer ID Application:"],
        )

        self.assertIn("Package/export step failed during macOS signing", message)


if __name__ == "__main__":
    unittest.main()
