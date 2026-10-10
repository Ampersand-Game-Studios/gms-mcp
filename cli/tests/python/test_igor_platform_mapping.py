#!/usr/bin/env python3
"""
Focused tests for Igor platform token mapping and prefab auto-detection.

These cover macOS-specific behavior without requiring Igor or a runtime install.
"""

import os
import sys
import tempfile
import unittest
import zipfile
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
        self._igor_idle_patch = patch.object(GameMakerRunner, "_wait_for_igor_idle")
        self._igor_idle_patch.start()
        self.addCleanup(self._igor_idle_patch.stop)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("gms_helpers.runner_support.discovery.platform.system", return_value="Darwin")
    def test_prefabs_path_prefers_users_shared_on_macos(self, _mock_system):
        runner = GameMakerRunner(self.project_root)

        shared_prefabs = "/Users/Shared/GameMakerStudio2/Prefabs"

        def fake_exists(path_obj: Path) -> bool:
            # `Path` is OS-specific; normalize so this test is stable on Windows CI.
            return path_obj.as_posix() == shared_prefabs

        with patch.dict(os.environ, {}, clear=True):
            # On Windows, clearing env vars can break Path.home() resolution.
            with patch("gms_helpers.runner_support.discovery.Path.home", return_value=Path("/fake/home")):
                with patch("gms_helpers.runner_support.discovery.Path.exists", autospec=True, side_effect=fake_exists):
                    found = runner.get_prefabs_path()

        self.assertIsNotNone(found)
        self.assertEqual(found.as_posix(), shared_prefabs)


class TestRunnerCommandSelection(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.tmp_dir)
        (self.project_root / "test_project.yyp").write_text('{"name": "test_project", "resources": []}')
        self._igor_idle_patch = patch.object(GameMakerRunner, "_wait_for_igor_idle")
        self._igor_idle_patch.start()
        self.addCleanup(self._igor_idle_patch.stop)

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

    @staticmethod
    def _write_android_package(path: Path, marker: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest_name = "AndroidManifest.xml" if path.suffix == ".apk" else "base/manifest/AndroidManifest.xml"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(manifest_name, "manifest")
            if marker:
                archive.writestr("assets/marker", marker)

    @patch.object(GameMakerRunner, "_wait_for_macos_main_loop", return_value=True)
    @patch.object(GameMakerRunner, "_wait_for_macos_runner_start", return_value=(20, {20}, set()))
    @patch.object(GameMakerRunner, "_stop_platform_process", return_value=True)
    def test_compile_project_uses_local_run_validation_on_macos(self, _mock_stop, _mock_runner, _mock_wait):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []

        def fake_run_igor(cmd, **_kwargs):
            captured_cmd[:] = cmd
            return self._fake_process()

        with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                        with patch.object(runner, "_reject_foreign_igor_after_launch"):
                            ok = runner.compile_project(platform_target="macOS", runtime_type="VM")

        self.assertTrue(ok)
        self.assertIn("Run", captured_cmd)
        self.assertNotIn("PackageZip", captured_cmd)
        self.assertNotIn("Tests", captured_cmd)
        self.assertFalse(any(str(arg).startswith("--tf=") for arg in captured_cmd))

    def test_compile_project_keeps_packagezip_on_windows(self):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []

        def fake_run_igor(cmd, **_kwargs):
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

    def test_compile_project_uses_package_on_linux(self):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []

        def fake_run_igor(cmd, **_kwargs):
            captured_cmd[:] = cmd
            return self._fake_process()

        with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                        ok = runner.compile_project(platform_target="Linux", runtime_type="VM")

        self.assertTrue(ok)
        self.assertNotIn("Compile", captured_cmd)
        self.assertIn("Package", captured_cmd)
        self.assertNotIn("PackageZip", captured_cmd)
        self.assertNotIn("Tests", captured_cmd)
        self.assertTrue(any(str(arg).startswith("/of=") for arg in captured_cmd))

    def test_html5_target_type_exception_succeeds_only_with_verified_artifact(self):
        runner = GameMakerRunner(self.project_root)
        system_temp = self.project_root / "temp"
        package_root = system_temp / "GameMakerStudio2" / "test_project" / "html5game"
        package_root.mkdir(parents=True)
        (package_root / "index.html").write_text("<script src='game.js'></script>", encoding="utf-8")
        (package_root / "game.js").write_text("window.game = true;", encoding="utf-8")
        process = self._fake_process()
        process.returncode = 1
        output = [
            "Final Compile finished",
            "Saving IFF file",
            "Igor complete.",
            "The given key (targetType) was not present in the dictionary",
        ]

        with patch.object(runner, "find_project_file", return_value=self.project_root / "test_project.yyp"):
            with patch.object(runner, "_system_temp_root", return_value=system_temp):
                with patch.object(runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                    with patch.object(runner, "_run_igor_command", return_value=process):
                        with patch.object(runner, "_stream_igor_output", return_value=output):
                            self.assertTrue(runner.compile_project(platform_target="HTML5"))

        (package_root / "index.html").unlink()
        with patch.object(runner, "find_project_file", return_value=self.project_root / "test_project.yyp"):
            with patch.object(runner, "_system_temp_root", return_value=system_temp):
                with patch.object(runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                    with patch.object(runner, "_run_igor_command", return_value=process):
                        with patch.object(runner, "_stream_igor_output", return_value=output):
                            self.assertFalse(runner.compile_project(platform_target="HTML5"))

    def test_macos_temp_run_uses_local_run_without_tf(self):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []

        def fake_run_igor(cmd, **_kwargs):
            captured_cmd[:] = cmd
            return self._fake_process()

        with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                        with patch.object(runner, "_reject_foreign_igor_after_launch"):
                            with patch.object(runner, "_collect_igor_output_async", return_value=([], MagicMock())):
                                with (
                                    patch.object(
                                        runner,
                                        "_wait_for_macos_runner_start",
                                        return_value=(222, {222}, {333}),
                                    ),
                                    patch.object(runner, "_snapshot_macos_processes", return_value={}),
                                ):
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

    def test_compile_project_uses_package_on_android(self):
        runner = GameMakerRunner(self.project_root)
        captured_cmd = []
        system_temp = self.project_root / "temp"
        package_path = system_temp / "GameMakerStudio2" / "test_project" / "test_project.apk"

        def fake_run_igor(cmd, **_kwargs):
            captured_cmd[:] = cmd
            self._write_android_package(package_path)
            return self._fake_process()

        with patch.object(runner, "_system_temp_root", return_value=system_temp):
            with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
                with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                    with patch.object(runner, "get_prefabs_path", return_value=None):
                        with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                            ok = runner.compile_project(platform_target="Android", runtime_type="VM")

        self.assertTrue(ok)
        self.assertIn("Package", captured_cmd)
        self.assertNotIn("PackageZip", captured_cmd)

    def test_compile_project_rejects_android_package_without_apk_or_aab(self):
        runner = GameMakerRunner(self.project_root)
        process = self._fake_process()
        system_temp = self.project_root / "temp"

        with patch.object(runner, "_system_temp_root", return_value=system_temp):
            with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
                with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                    with patch.object(runner, "get_prefabs_path", return_value=None):
                        with patch.object(runner, "_run_igor_command", return_value=process):
                            self.assertFalse(runner.compile_project(platform_target="Android", runtime_type="VM"))

        self.assertIn("APK or AAB", runner.last_failure_message)

    def test_compile_project_rejects_stale_android_package(self):
        runner = GameMakerRunner(self.project_root)
        process = self._fake_process()
        system_temp = self.project_root / "temp"
        package_path = system_temp / "GameMakerStudio2" / "test_project" / "test_project.aab"
        self._write_android_package(package_path)

        with patch.object(runner, "_system_temp_root", return_value=system_temp):
            with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
                with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                    with patch.object(runner, "get_prefabs_path", return_value=None):
                        with patch.object(runner, "_run_igor_command", return_value=process):
                            self.assertFalse(runner.compile_project(platform_target="Android", runtime_type="VM"))

        self.assertIn("new verified APK or AAB", runner.last_failure_message)

    def test_compile_project_rejects_invalid_android_package_artifacts(self):
        system_temp = self.project_root / "temp"
        package_dir = system_temp / "GameMakerStudio2" / "test_project"
        package_dir.mkdir(parents=True)

        def write_empty(path: Path) -> None:
            path.touch()

        def write_corrupt(path: Path) -> None:
            path.write_bytes(b"not a zip")

        def write_missing_manifest(path: Path) -> None:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("assets/game.droid", "game")

        for suffix, writer in ((".apk", write_empty), (".aab", write_corrupt), (".apk", write_missing_manifest)):
            with self.subTest(suffix=suffix, writer=writer.__name__):
                runner = GameMakerRunner(self.project_root)
                package_path = package_dir / f"invalid-{writer.__name__}{suffix}"
                writer(package_path)

                with patch.object(runner, "_system_temp_root", return_value=system_temp):
                    with patch.object(
                        runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)
                    ):
                        with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                            with patch.object(runner, "get_prefabs_path", return_value=None):
                                with patch.object(runner, "_run_igor_command", return_value=self._fake_process()):
                                    self.assertFalse(
                                        runner.compile_project(platform_target="Android", runtime_type="VM")
                                    )

                self.assertIn("new verified APK or AAB", runner.last_failure_message)

    def test_compile_project_accepts_fresh_valid_android_aab(self):
        runner = GameMakerRunner(self.project_root)
        system_temp = self.project_root / "temp"
        package_path = system_temp / "GameMakerStudio2" / "test_project" / "test_project.aab"

        def fake_run_igor(_cmd, **_kwargs):
            self._write_android_package(package_path)
            return self._fake_process()

        with patch.object(runner, "_system_temp_root", return_value=system_temp):
            with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
                with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                    with patch.object(runner, "get_prefabs_path", return_value=None):
                        with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                            self.assertTrue(runner.compile_project(platform_target="Android", runtime_type="VM"))

    def test_compile_project_accepts_rewritten_android_package(self):
        runner = GameMakerRunner(self.project_root)
        system_temp = self.project_root / "temp"
        package_path = system_temp / "GameMakerStudio2" / "test_project" / "test_project.apk"
        self._write_android_package(package_path, marker="old")

        def fake_run_igor(_cmd, **_kwargs):
            self._write_android_package(package_path, marker="new")
            return self._fake_process()

        with patch.object(runner, "_system_temp_root", return_value=system_temp):
            with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
                with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                    with patch.object(runner, "get_prefabs_path", return_value=None):
                        with patch.object(runner, "_run_igor_command", side_effect=fake_run_igor):
                            self.assertTrue(runner.compile_project(platform_target="Android", runtime_type="VM"))

    def test_compile_project_rejects_unknown_igor_command_with_zero_exit(self):
        runner = GameMakerRunner(self.project_root)
        process = self._fake_process()

        with patch.object(runner, "find_gamemaker_runtime", side_effect=lambda: self._fake_find_runtime(runner)):
            with patch.object(runner, "find_license_file", return_value=Path("/fake/licence.plist")):
                with patch.object(runner, "get_prefabs_path", return_value=None):
                    with patch.object(runner, "_run_igor_command", return_value=process):
                        with patch.object(
                            runner,
                            "_stream_igor_output",
                            return_value=["Igor: Unknown command PackageZip"],
                        ):
                            ok = runner.compile_project(platform_target="Windows", runtime_type="VM")

        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
