#!/usr/bin/env python3
"""Targeted coverage tests for runner.py helper and control-flow paths."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.exceptions import LicenseNotFoundError, ProjectNotFoundError, RuntimeNotFoundError
from gms_helpers.runner import (
    GameMakerRunner,
    _to_igor_platform,
    compile_project as compile_project_wrapper,
    detect_default_target_platform,
    get_project_status,
    normalize_platform_target,
    run_project as run_project_wrapper,
    stop_project,
)


class TestRunnerGapCoverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "TestGame.yyp").write_text('{"resources": []}', encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_runner(self) -> GameMakerRunner:
        return GameMakerRunner(self.project_root)

    def test_platform_helpers_and_state_helpers(self):
        with patch("gms_helpers.runner.platform.system", return_value="Linux"):
            self.assertEqual(detect_default_target_platform(), "Linux")
        with patch("gms_helpers.runner.platform.system", return_value="Darwin"):
            self.assertEqual(detect_default_target_platform(), "macOS")

        self.assertEqual(normalize_platform_target("android"), "Android")
        self.assertEqual(normalize_platform_target(" custom "), " custom ")
        self.assertEqual(_to_igor_platform("macOS"), "Mac")

        runner = self._make_runner()
        with patch("gms_helpers.runner.platform.system", return_value="Windows"):
            self.assertEqual(runner._normalize_path_for_popen(), {})
        with patch("gms_helpers.runner.platform.system", return_value="Linux"):
            self.assertEqual(runner._normalize_path_for_popen(), {"start_new_session": True})

        cmd = ["igor"]
        runner._append_runtime_type_arg(cmd, "YYC")
        self.assertIn("/runtime=YYC", cmd)
        runner._clear_last_result("compile")
        runner._remember_failure("failed")
        self.assertEqual(runner.last_action_label, "compile")
        self.assertEqual(runner.last_failure_message, "failed")

    def test_find_project_file_and_runtime_selection(self):
        runner = self._make_runner()
        self.assertEqual(runner.find_project_file().name, "TestGame.yyp")

        sub_root = Path(tempfile.mkdtemp())
        try:
            (sub_root / "gamemaker").mkdir()
            (sub_root / "gamemaker" / "Game.yyp").write_text("{}", encoding="utf-8")
            runner = GameMakerRunner(sub_root)
            with patch("gms_helpers.runner.find_yyp", side_effect=[SystemExit(), sub_root / "gamemaker" / "Game.yyp"]):
                self.assertEqual(runner.find_project_file().name, "Game.yyp")
            self.assertEqual(runner.project_root, (sub_root / "gamemaker").resolve())

            runner = GameMakerRunner(sub_root)
            with patch("gms_helpers.runner.find_yyp", side_effect=[SystemExit(), SystemExit()]):
                with self.assertRaises(FileNotFoundError):
                    runner.find_project_file()
        finally:
            shutil.rmtree(sub_root, ignore_errors=True)

        missing_root = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(ProjectNotFoundError):
                GameMakerRunner(missing_root).find_project_file()
        finally:
            shutil.rmtree(missing_root, ignore_errors=True)

        runner = self._make_runner()
        runtime_info = SimpleNamespace(is_valid=True, igor_path="/fake/Igor", path="/fake/runtime")
        with patch.object(runner._runtime_manager, "select", return_value=runtime_info) as mock_select:
            self.assertEqual(runner.find_gamemaker_runtime(), Path("/fake/Igor"))
            self.assertEqual(runner.runtime_path, Path("/fake/runtime"))
            self.assertEqual(runner.find_gamemaker_runtime(), Path("/fake/Igor"))
        mock_select.assert_called_once()

        runner = self._make_runner()
        with patch.object(runner._runtime_manager, "select", return_value=None):
            self.assertIsNone(runner.find_gamemaker_runtime())

    def test_prefabs_license_and_base_command(self):
        runner = self._make_runner()
        prefabs_dir = self.project_root / "Prefabs"
        prefabs_dir.mkdir()
        with patch.dict(os.environ, {"GMS_PREFABS_PATH": str(prefabs_dir)}, clear=True):
            self.assertEqual(runner.get_prefabs_path(), prefabs_dir)

        home_dir = self.project_root / "home"
        license_dir = home_dir / ".config" / "GameMakerStudio2" / "user_1"
        license_dir.mkdir(parents=True)
        license_path = license_dir / "license.plist"
        license_path.write_text("<plist/>", encoding="utf-8")
        with patch("gms_helpers.runner.platform.system", return_value="Linux"):
            with patch("gms_helpers.runner.Path.home", return_value=home_dir):
                self.assertEqual(runner.find_license_file(), license_path)

        nested_root = self.project_root / "nested-home"
        nested_user = nested_root / ".config" / "GameMakerStudio2" / "user_2"
        nested_license_dir = nested_user / "nested"
        nested_license_dir.mkdir(parents=True)
        older = nested_license_dir / "licence.plist"
        newer = nested_license_dir / "license.plist"
        older.write_text("old", encoding="utf-8")
        newer.write_text("new", encoding="utf-8")
        os.utime(older, (older.stat().st_atime, older.stat().st_mtime - 10))
        with patch("gms_helpers.runner.platform.system", return_value="Linux"):
            with patch("gms_helpers.runner.Path.home", return_value=nested_root):
                self.assertEqual(runner.find_license_file(), newer)

        with patch.object(runner, "find_gamemaker_runtime", return_value=Path("/fake/Igor")):
            runner.runtime_path = Path("/fake/runtime")
            with patch.object(runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(runner, "find_license_file", return_value=Path("/fake/license.plist")):
                    with patch.object(runner, "get_prefabs_path", return_value=Path("/fake/Prefabs")):
                        cmd = runner._build_igor_base_command()
        self.assertIn("/lf=/fake/license.plist", cmd)
        self.assertIn("/rp=/fake/runtime", cmd)
        self.assertIn("--pf=/fake/Prefabs", cmd)

        with patch.object(runner, "find_gamemaker_runtime", return_value=None):
            with self.assertRaises(RuntimeNotFoundError):
                runner._build_igor_base_command()

        with patch.object(runner, "find_gamemaker_runtime", return_value=Path("/fake/Igor")):
            runner.runtime_path = Path("/fake/runtime")
            with patch.object(runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(runner, "find_license_file", return_value=None):
                    with self.assertRaises(LicenseNotFoundError):
                        runner._build_igor_base_command()

    def test_launch_guidance_and_launch_target_helpers(self):
        runner = self._make_runner()
        target = Path("/fake/app")
        self.assertIn("permission", runner._build_macos_launch_guidance(target, OSError(errno.EACCES, "Permission denied"), "game").lower())
        self.assertIn("sandbox", runner._build_macos_launch_guidance(target, OSError(errno.EPERM, "operation not permitted"), "runtime").lower())
        self.assertIn("code signing", runner._build_macos_launch_guidance(target, OSError(2, "code signature invalid"), "runtime").lower())

        app_bundle = self.project_root / "Game.app" / "Contents" / "MacOS"
        app_bundle.mkdir(parents=True)
        binary = app_bundle / "Game"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
        self.assertEqual(runner._find_macos_app_binary(self.project_root / "Game.app"), binary)

        build_dir = self.project_root / "build"
        build_dir.mkdir()
        exe = build_dir / "TestGame.exe"
        exe.write_text("bin", encoding="utf-8")
        self.assertEqual(runner._find_launch_target(build_dir, "TestGame", "Windows"), exe)
        exe.unlink()

        mac_app = build_dir / "Runner.app" / "Contents" / "MacOS"
        mac_app.mkdir(parents=True)
        mac_bin = mac_app / "Runner"
        mac_bin.write_text("bin", encoding="utf-8")
        mac_bin.chmod(mac_bin.stat().st_mode | stat.S_IXUSR)
        self.assertEqual(runner._find_launch_target(build_dir, "TestGame", "macOS"), mac_bin)

        linux_bin = build_dir / "runner"
        linux_bin.write_text("bin", encoding="utf-8")
        linux_bin.chmod(linux_bin.stat().st_mode | stat.S_IXUSR)
        self.assertEqual(runner._find_launch_target(build_dir, "TestGame", "Linux"), linux_bin)

        with patch("gms_helpers.runner.platform.system", return_value="Darwin"):
            with patch("gms_helpers.runner.subprocess.Popen", side_effect=OSError(errno.EACCES, "Permission denied")):
                with self.assertRaises(RuntimeError):
                    runner._start_game_process(Path("/fake/game"))
            with patch("gms_helpers.runner.subprocess.Popen", side_effect=OSError(errno.EACCES, "Permission denied")):
                with self.assertRaises(RuntimeError):
                    runner._run_igor_command(["/fake/Igor"])

    def test_streaming_ps_and_wait_helpers(self):
        runner = self._make_runner()
        process = SimpleNamespace(
            stdout=iter(
                [
                    "compile starting\n",
                    "warning: thing\n",
                    "error: bad\n",
                    "export bundle\n",
                    "plain line\n",
                ]
            )
        )
        lines = runner._stream_igor_output(process, "package/export")
        self.assertEqual(len(lines), 5)
        self.assertTrue(runner._is_macos_signing_failure(["codesign failed"]))
        self.assertFalse(runner._is_macos_signing_failure(["all good"]))
        self.assertIn("Local compile validation failed", runner._build_stage_failure_message("local compile validation", 2, []))
        self.assertIn("Local run failed", runner._build_stage_failure_message("local run", 3, []))
        self.assertIn("Compile failed", runner._build_stage_failure_message("compile", 4, []))

        async_process = SimpleNamespace(stdout=iter(["test run\n"]))
        output_lines, thread = runner._collect_igor_output_async(async_process, "local compile validation")
        thread.join(timeout=2)
        self.assertEqual(output_lines, ["test run"])

        game_path = Path("/tmp/game.ios")
        debug_log_path = Path("/tmp/debug.log")
        ps_output = (
            f"101 /tmp/Game.app/Contents/MacOS/Mac_Runner {game_path}\n"
            f"102 tail -F {debug_log_path}\n"
        )
        with patch("gms_helpers.runner.subprocess.run", return_value=SimpleNamespace(stdout=ps_output)):
            runner_pids, tail_pids = runner._find_macos_validation_helper_pids(game_path, debug_log_path)
        self.assertEqual(runner_pids, {101})
        self.assertEqual(tail_pids, {102})

        debug_log = self.project_root / "debug.log"
        debug_log.write_text("prefix\nEntering main loop.\n", encoding="utf-8")
        proc = MagicMock()
        proc.poll.return_value = None
        self.assertTrue(runner._wait_for_macos_main_loop(proc, debug_log, 0, timeout_seconds=0.1))

        proc = MagicMock()
        proc.poll.side_effect = [None, None]
        with patch.object(
            runner,
            "_find_macos_validation_helper_pids",
            side_effect=[({1}, set()), ({1, 2}, {3})],
        ):
            pid, runner_pids, tail_pids = runner._wait_for_macos_runner_start(
                proc,
                Path("/tmp/game.ios"),
                Path("/tmp/debug.log"),
                {1},
                set(),
                timeout_seconds=0.1,
            )
        self.assertEqual(pid, 2)
        self.assertEqual(runner_pids, {2})
        self.assertEqual(tail_pids, {3})

        completed = SimpleNamespace(returncode=0, stdout="stopped\n")
        with patch.object(runner, "_build_platform_action_command", return_value=["igor", "Stop"]):
            with patch("gms_helpers.runner.subprocess.run", return_value=completed):
                self.assertTrue(runner._stop_platform_process("Windows"))

        kill_calls = []

        def fake_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == 0:
                raise ProcessLookupError()

        with patch("gms_helpers.runner.os.kill", side_effect=fake_kill):
            runner._terminate_pid(123, "runner")
        self.assertEqual(kill_calls[0][1], __import__("signal").SIGTERM)

        terminated = []
        with patch.object(runner, "_find_macos_validation_helper_pids", return_value=({1, 2}, {3})):
            with patch.object(runner, "_terminate_pid", side_effect=lambda pid, _label: terminated.append(pid)):
                runner._cleanup_macos_validation_helpers(Path("/tmp/game.ios"), Path("/tmp/debug.log"), {1}, set())
        self.assertEqual(sorted(terminated), [2, 3])

    def test_compile_and_run_paths(self):
        runner = self._make_runner()
        fake_process = MagicMock()
        fake_process.stdout = None
        fake_process.returncode = 0
        fake_process.poll.side_effect = [None, None, None]

        with patch.object(runner, "_build_macos_compile_validation_command", return_value=["igor", "Run"]):
            with patch.object(runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(runner, "_macos_debug_log_path", return_value=self.project_root / "debug.log"):
                    with patch.object(runner, "_run_igor_command", return_value=fake_process):
                        with patch.object(runner, "_collect_igor_output_async", return_value=([], MagicMock(join=lambda timeout=0: None))):
                            with patch.object(runner, "_wait_for_macos_main_loop", return_value=False):
                                with patch.object(runner, "_stop_platform_process", return_value=True):
                                    with patch.object(runner, "_cleanup_macos_validation_helpers"):
                                        self.assertFalse(runner.compile_project(platform_target="macOS"))
        self.assertIn("main loop", runner.last_failure_message)

        failing_process = MagicMock()
        failing_process.stdout = None
        failing_process.returncode = 2
        failing_process.wait.return_value = 2
        with patch.object(runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
            with patch.object(runner, "_system_temp_root", return_value=self.project_root / "tmp"):
                with patch.object(runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                    with patch.object(runner, "_run_igor_command", return_value=failing_process):
                        with patch.object(runner, "_stream_igor_output", return_value=["codesign failed"]):
                            self.assertFalse(runner.compile_project(platform_target="Windows"))

        launch_process = MagicMock()
        launch_process.pid = 777
        package_process = MagicMock()
        package_process.stdout = None
        package_process.returncode = 0
        package_process.wait.return_value = 0
        launch_path = self.project_root / "tmp" / "GameMakerStudio2" / "TestGame" / "TestGame.exe"
        launch_path.parent.mkdir(parents=True, exist_ok=True)
        launch_path.write_text("bin", encoding="utf-8")
        with patch.object(runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
            with patch.object(runner, "_system_temp_root", return_value=self.project_root / "tmp"):
                with patch.object(runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                    with patch.object(runner, "_run_igor_command", return_value=package_process):
                        with patch.object(runner, "_stream_igor_output", return_value=[]):
                            with patch.object(runner, "_find_launch_target", return_value=launch_path):
                                with patch.object(runner, "_start_game_process", return_value=launch_process):
                                    result = runner._run_project_ide_temp_approach(platform_target="Windows", background=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 777)

        classic_process = MagicMock()
        classic_process.pid = 1234
        classic_process.stdout = iter(["build ok\n"])
        classic_process.returncode = 0
        classic_process.wait.return_value = 0
        with patch.object(runner, "_build_platform_action_command", return_value=["igor", "Run"]):
            with patch.object(runner, "_run_igor_command", return_value=classic_process):
                self.assertTrue(runner._run_project_classic_approach(platform_target="Windows", background=False))

    def test_wrapper_functions(self):
        with patch("gms_helpers.runner.GameMakerRunner") as mock_runner_class:
            runner = mock_runner_class.return_value
            runner.compile_project.return_value = True
            runner.run_project_direct.return_value = {"ok": True}
            runner.stop_game.return_value = {"ok": True}
            runner.get_game_status.return_value = {"running": False}

            self.assertTrue(compile_project_wrapper(str(self.project_root)))
            self.assertEqual(run_project_wrapper(str(self.project_root), background=True), {"ok": True})
            self.assertEqual(stop_project(str(self.project_root)), {"ok": True})
            self.assertEqual(get_project_status(str(self.project_root)), {"running": False})


if __name__ == "__main__":
    unittest.main()
