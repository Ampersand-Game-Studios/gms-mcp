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
            return str(path_obj) == shared_prefabs

        with patch.dict(os.environ, {}, clear=True):
            with patch("gms_helpers.runner.Path.exists", autospec=True, side_effect=fake_exists):
                found = runner.get_prefabs_path()

        self.assertIsNotNone(found)
        self.assertEqual(str(found), shared_prefabs)


class TestMacPackageZipTargetFilename(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.tmp_dir)
        (self.project_root / "test_project.yyp").write_text('{"name": "test_project", "resources": []}')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_compile_project_adds_tf_for_macos(self):
        runner = GameMakerRunner(self.project_root)

        captured_cmd = []

        def fake_find_runtime():
            runner.runtime_path = Path("/fake/runtime")
            return Path("/fake/Igor")

        def fake_run_igor(cmd):
            captured_cmd[:] = cmd
            proc = MagicMock()
            proc.stdout = None
            proc.wait.return_value = 0
            proc.returncode = 0
            return proc

        with patch.object(runner, "find_gamemaker_runtime", side_effect=fake_find_runtime):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                        ok = runner.compile_project(platform_target="macOS", runtime_type="VM")

        self.assertTrue(ok)
        self.assertTrue(any(str(arg).startswith("--tf=") for arg in captured_cmd))


if __name__ == "__main__":
    unittest.main()
