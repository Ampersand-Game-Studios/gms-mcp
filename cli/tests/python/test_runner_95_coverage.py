#!/usr/bin/env python3
"""Additional coverage tests for runner.py to drive the module above 95%."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.runner import GameMakerRunner


class TestRunner95Coverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "TestGame.yyp").write_text('{"resources": []}', encoding="utf-8")
        self.runner = GameMakerRunner(self.project_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prefabs_license_and_launch_target_remaining_paths(self):
        with patch("gms_helpers.runner.platform.system", return_value="Windows"):
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(self.runner.get_prefabs_path())

        with patch("gms_helpers.runner.platform.system", return_value="Linux"):
            with patch.dict(os.environ, {}, clear=True):
                with patch("gms_helpers.runner.Path.home", return_value=self.project_root / "home"):
                    self.assertIsNone(self.runner.get_prefabs_path())

        with patch("gms_helpers.runner.platform.system", return_value="Windows"):
            with patch.dict(os.environ, {"USERNAME": "tester"}, clear=True):
                with patch("gms_helpers.runner.Path.home", return_value=self.project_root / "missing-home"):
                    self.assertIsNone(self.runner.find_license_file())

        linux_home = self.project_root / "linux-home"
        base_dir = linux_home / ".config" / "GameMakerStudio2"
        base_dir.mkdir(parents=True)
        direct_license = base_dir / "license.plist"
        direct_license.write_text("<plist/>", encoding="utf-8")
        with patch("gms_helpers.runner.platform.system", return_value="Linux"):
            with patch("gms_helpers.runner.Path.home", return_value=linux_home):
                self.assertEqual(self.runner.find_license_file(), direct_license)

        self.assertIn(
            "failed for macOS",
            self.runner._build_macos_launch_guidance(Path("/fake/app"), OSError(errno.ENOENT, "boom"), "runtime"),
        )
        self.assertIsNone(self.runner._find_macos_app_binary(self.project_root / "Missing.app"))

        build_dir = self.project_root / "build"
        build_dir.mkdir()
        self.assertIsNone(self.runner._find_launch_target(build_dir, "TestGame", "Windows"))

        wildcard_app = build_dir / "Wildcard.app" / "Contents" / "MacOS"
        wildcard_app.mkdir(parents=True)
        wildcard_bin = wildcard_app / "Wildcard"
        wildcard_bin.write_text("bin", encoding="utf-8")
        wildcard_bin.chmod(wildcard_bin.stat().st_mode | stat.S_IXUSR)
        self.assertEqual(self.runner._find_launch_target(build_dir, "TestGame", "macOS"), wildcard_bin)

        linux_dir = self.project_root / "linux-build"
        linux_dir.mkdir()
        custom_bin = linux_dir / "CustomGame"
        custom_bin.write_text("bin", encoding="utf-8")
        custom_bin.chmod(custom_bin.stat().st_mode | stat.S_IXUSR)
        self.assertEqual(self.runner._find_launch_target(linux_dir, "Nope", "Linux"), custom_bin)

    def test_wait_ps_and_terminate_remaining_paths(self):
        lines = self.runner._stream_igor_output(SimpleNamespace(stdout=iter(["\n", "plain\n"])), "package/export")
        self.assertEqual(lines, ["plain"])

        missing_log = self.project_root / "missing.log"
        process = MagicMock()
        process.poll.side_effect = [1]
        with patch("gms_helpers.runner.time.monotonic", side_effect=[0.0, 0.1, 2.0]):
            with patch("gms_helpers.runner.time.sleep"):
                self.assertFalse(self.runner._wait_for_macos_main_loop(process, missing_log, 0, timeout_seconds=1.0))

        bad_log = self.project_root / "debug.log"
        bad_log.write_text("ignored", encoding="utf-8")
        process = MagicMock()
        process.poll.side_effect = [None, 1]
        with patch.object(Path, "open", side_effect=OSError("bad log")):
            with patch("gms_helpers.runner.time.monotonic", side_effect=[0.0, 0.1, 2.0]):
                with patch("gms_helpers.runner.time.sleep"):
                    self.assertFalse(self.runner._wait_for_macos_main_loop(process, bad_log, 0, timeout_seconds=1.0))

        process = MagicMock()
        process.poll.return_value = 1
        with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=({1}, {2})):
            with patch("gms_helpers.runner.time.monotonic", side_effect=[0.0, 2.0]):
                with patch("gms_helpers.runner.time.sleep"):
                    pid, runner_pids, tail_pids = self.runner._wait_for_macos_runner_start(
                        process,
                        Path("/tmp/game.ios"),
                        Path("/tmp/debug.log"),
                        {1},
                        {2},
                        timeout_seconds=1.0,
                    )
        self.assertIsNone(pid)
        self.assertEqual(runner_pids, set())
        self.assertEqual(tail_pids, set())

        game_path = Path("/tmp/game.ios")
        debug_log = Path("/tmp/debug.log")
        ps_output = f"\ninvalid\nnot_a_pid command\n101 /tmp/Game.app/Contents/MacOS/Mac_Runner {game_path}\n"
        with patch("gms_helpers.runner.subprocess.run", return_value=SimpleNamespace(stdout=ps_output)):
            runner_pids, tail_pids = self.runner._find_macos_validation_helper_pids(game_path, debug_log)
        self.assertEqual(runner_pids, {101})
        self.assertEqual(tail_pids, set())

        with patch("gms_helpers.runner.os.kill", side_effect=RuntimeError("blocked")):
            self.runner._terminate_pid(10, "runner")

        kill_calls = []

        def stubborn_kill(pid, sig):
            kill_calls.append(sig)
            if sig == 0:
                return None
            if sig == __import__("signal").SIGKILL:
                raise RuntimeError("cannot kill")

        with patch("gms_helpers.runner.os.kill", side_effect=stubborn_kill):
            with patch("gms_helpers.runner.time.monotonic", side_effect=[0.0, 0.1, 6.0]):
                with patch("gms_helpers.runner.time.sleep"):
                    self.runner._terminate_pid(20, "runner")
        self.assertIn(__import__("signal").SIGKILL, kill_calls)

    def test_stop_macos_session_remaining_paths(self):
        session = SimpleNamespace(pid=99, exe_path="/tmp/game.ios", log_file="/tmp/debug.log", runtime_type="VM")
        with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=({10}, {20})):
            with patch.object(self.runner, "_stop_platform_process", return_value=True):
                with patch.object(self.runner._session_manager, "is_process_alive", return_value=False):
                    with patch.object(self.runner._session_manager, "clear_session") as mock_clear:
                        result = self.runner._stop_macos_run_session(session)
        self.assertTrue(result["ok"])
        mock_clear.assert_called_once()

        with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=({10}, {20})):
            with patch.object(self.runner, "_stop_platform_process", return_value=False):
                with patch.object(
                    self.runner._session_manager,
                    "is_process_alive",
                    return_value=True,
                ):
                    with patch.object(self.runner, "_terminate_pid"):
                        with patch.object(self.runner._session_manager, "clear_session"):
                            with patch("gms_helpers.runner.time.monotonic", side_effect=[0.0, 6.0]):
                                result = self.runner._stop_macos_run_session(session)
        self.assertFalse(result["ok"])
        self.assertIn("still alive", result["message"])

        call_counter = {"count": 0}

        def cleanup_alive(pid):
            call_counter["count"] += 1
            return call_counter["count"] <= 3

        with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=({10}, {20})):
            with patch.object(self.runner, "_stop_platform_process", return_value=False):
                with patch.object(
                    self.runner._session_manager,
                    "is_process_alive",
                    side_effect=cleanup_alive,
                ):
                    with patch.object(self.runner, "_terminate_pid"):
                        with patch.object(self.runner._session_manager, "clear_session"):
                            with patch("gms_helpers.runner.time.monotonic", side_effect=[0.0, 6.0]):
                                result = self.runner._stop_macos_run_session(session)
        self.assertTrue(result["ok"])
        self.assertIn("manual cleanup", result["message"])

    def test_compile_project_remaining_paths(self):
        process = MagicMock()
        process.poll.side_effect = [None, None]
        process.wait.side_effect = [subprocess.TimeoutExpired(cmd="igor", timeout=10), None]
        process.returncode = 1
        thread = SimpleNamespace(join=lambda timeout=0: None)

        with patch.object(self.runner, "_build_macos_compile_validation_command", return_value=["igor", "Run"]):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_macos_debug_log_path", return_value=self.project_root / "debug.log"):
                    with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=(set(), set())):
                        with patch.object(self.runner, "_run_igor_command", return_value=process):
                            with patch.object(self.runner, "_collect_igor_output_async", return_value=(["bad"], thread)):
                                with patch.object(self.runner, "_wait_for_macos_main_loop", return_value=False):
                                    with patch.object(self.runner, "_stop_platform_process", return_value=False):
                                        with patch.object(self.runner, "_cleanup_macos_validation_helpers"):
                                            self.assertFalse(self.runner.compile_project(platform_target="macOS"))
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertIn("timed out", self.runner.last_failure_message)

        process = MagicMock()
        process.poll.side_effect = [0, 0]
        process.returncode = 0
        thread = SimpleNamespace(join=lambda timeout=0: None)
        with patch.object(self.runner, "_build_macos_compile_validation_command", return_value=["igor", "Run"]):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_macos_debug_log_path", return_value=self.project_root / "debug.log"):
                    with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=(set(), set())):
                        with patch.object(self.runner, "_run_igor_command", return_value=process):
                            with patch.object(self.runner, "_collect_igor_output_async", return_value=([], thread)):
                                with patch.object(self.runner, "_wait_for_macos_main_loop", return_value=False):
                                    with patch.object(self.runner, "_cleanup_macos_validation_helpers"):
                                        self.assertFalse(self.runner.compile_project(platform_target="macOS"))
        self.assertIn("exited before the game reached the main loop", self.runner.last_failure_message)

        process = MagicMock()
        process.poll.side_effect = [2, 2]
        process.returncode = 2
        thread = SimpleNamespace(join=lambda timeout=0: None)
        with patch.object(self.runner, "_build_macos_compile_validation_command", return_value=["igor", "Run"]):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_macos_debug_log_path", return_value=self.project_root / "debug.log"):
                    with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=(set(), set())):
                        with patch.object(self.runner, "_run_igor_command", return_value=process):
                            with patch.object(self.runner, "_collect_igor_output_async", return_value=(["compile failed"], thread)):
                                with patch.object(self.runner, "_wait_for_macos_main_loop", return_value=False):
                                    with patch.object(self.runner, "_cleanup_macos_validation_helpers"):
                                        self.assertFalse(self.runner.compile_project(platform_target="macOS"))
        self.assertIn("Local compile validation failed", self.runner.last_failure_message)

        with patch.object(self.runner, "_build_platform_action_command", side_effect=RuntimeError("boom")):
            self.assertFalse(self.runner.compile_project(platform_target="Windows"))

    def test_ide_temp_run_remaining_paths(self):
        temp_root = self.project_root / "tmp"
        session = SimpleNamespace(run_id="run-1")

        package_process = MagicMock()
        package_process.returncode = 0
        package_process.wait.return_value = 0
        app_zip = temp_root / "GameMakerStudio2" / "TestGame" / "TestGame.app.zip"
        app_zip.parent.mkdir(parents=True, exist_ok=True)
        app_zip.write_text("zip", encoding="utf-8")
        launch_path = app_zip.parent / "TestGame"
        launch_path.write_text("bin", encoding="utf-8")

        game_process = MagicMock()
        game_process.pid = 777

        with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
            with patch.object(self.runner, "_system_temp_root", return_value=temp_root):
                with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                    with patch.object(self.runner, "_run_igor_command", return_value=package_process):
                        with patch.object(self.runner, "_stream_igor_output", return_value=[]):
                            with patch.object(self.runner, "_find_launch_target", return_value=launch_path):
                                with patch.object(self.runner, "_start_game_process", return_value=game_process):
                                    with patch.object(self.runner._session_manager, "create_session", return_value=session):
                                        with patch("gms_helpers.runner.subprocess.run") as mock_unzip:
                                            result = self.runner._run_project_ide_temp_approach(
                                                platform_target="macOS",
                                                background=True,
                                            )
        self.assertTrue(result["ok"])
        mock_unzip.assert_called_once()

        failed_package = MagicMock()
        failed_package.returncode = 2
        failed_package.wait.return_value = 2
        ide_dir = temp_root / "GameMakerStudio2" / "TestGame"
        ide_dir.mkdir(parents=True, exist_ok=True)
        (ide_dir / "artifact.txt").write_text("artifact", encoding="utf-8")
        with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
            with patch.object(self.runner, "_system_temp_root", return_value=temp_root):
                with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                    with patch.object(self.runner, "_run_igor_command", return_value=failed_package):
                        with patch.object(self.runner, "_stream_igor_output", return_value=["bad"]):
                            with patch.object(self.runner, "_find_launch_target", return_value=None):
                                self.assertFalse(self.runner._run_project_ide_temp_approach(platform_target="Windows"))

        ok_package = MagicMock()
        ok_package.returncode = 0
        ok_package.wait.return_value = 0
        fg_game = MagicMock()
        fg_game.pid = 88
        fg_game.returncode = 5
        fg_game.wait.return_value = 5
        with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
            with patch.object(self.runner, "_system_temp_root", return_value=temp_root):
                with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                    with patch.object(self.runner, "_run_igor_command", return_value=ok_package):
                        with patch.object(self.runner, "_stream_igor_output", return_value=[]):
                            with patch.object(self.runner, "_find_launch_target", return_value=launch_path):
                                with patch.object(self.runner, "_start_game_process", return_value=fg_game):
                                    with patch.object(self.runner._session_manager, "create_session", return_value=session):
                                        with patch.object(self.runner._session_manager, "clear_session"):
                                            self.assertFalse(self.runner._run_project_ide_temp_approach(platform_target="Windows", background=False))

        with patch.object(self.runner, "_run_igor_command", side_effect=RuntimeError("explode")):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_system_temp_root", return_value=temp_root):
                    with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]):
                        self.assertFalse(self.runner._run_project_ide_temp_approach(platform_target="Windows"))

    def test_classic_run_and_stop_game_remaining_paths(self):
        temp_root = self.project_root / "tmp"

        process = MagicMock()
        process.pid = 222
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired(cmd="igor", timeout=5), None]

        with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_macos_debug_log_path", return_value=self.project_root / "debug.log"):
                    with patch.object(self.runner, "_run_igor_command", return_value=process):
                        with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=(set(), set())):
                            with patch.object(self.runner, "_collect_igor_output_async", return_value=([], SimpleNamespace(join=lambda timeout=0: None))):
                                with patch.object(self.runner, "_wait_for_macos_runner_start", return_value=(None, set(), set())):
                                    result = self.runner._run_project_classic_approach(platform_target="macOS", background=True)
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["message"])

        process = MagicMock()
        process.pid = 333
        process.poll.return_value = 3
        process.returncode = 3
        with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_macos_debug_log_path", return_value=self.project_root / "debug.log"):
                    with patch.object(self.runner, "_run_igor_command", return_value=process):
                        with patch.object(self.runner, "_find_macos_validation_helper_pids", return_value=(set(), set())):
                            with patch.object(self.runner, "_collect_igor_output_async", return_value=(["bad"], SimpleNamespace(join=lambda timeout=0: None))):
                                with patch.object(self.runner, "_wait_for_macos_runner_start", return_value=(None, set(), set())):
                                    result = self.runner._run_project_classic_approach(platform_target="macOS", background=True)
        self.assertFalse(result["ok"])
        self.assertIn("Local run failed", result["message"])

        fg_process = MagicMock()
        fg_process.pid = 444
        fg_process.stdout = iter(["error line\n", "warning line\n", "compile line\n", "plain line\n"])
        fg_process.returncode = 4
        fg_process.wait.return_value = 4
        with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_run_igor_command", return_value=fg_process):
                    with patch.object(self.runner._session_manager, "create_session", return_value=SimpleNamespace(run_id="run-2")):
                        with patch.object(self.runner._session_manager, "clear_session"):
                            self.assertFalse(self.runner._run_project_classic_approach(platform_target="Windows", background=False))

        with patch.object(self.runner, "_run_igor_command", side_effect=RuntimeError("bad run")):
            with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]):
                self.assertFalse(self.runner._run_project_classic_approach(platform_target="Windows", background=False))

        with patch.object(self.runner, "_run_project_classic_approach", return_value=True) as mock_classic:
            self.assertTrue(self.runner.run_project_direct(platform_target="Windows", output_location="project"))
        mock_classic.assert_called_once()

        local_process = MagicMock()
        local_process.poll.return_value = None
        local_process.wait.side_effect = subprocess.TimeoutExpired(cmd="igor", timeout=3)
        self.runner.game_process = local_process
        with patch.object(self.runner._session_manager, "get_current_session", return_value=None):
            with patch.object(self.runner._session_manager, "stop_game", return_value={"ok": True}):
                result = self.runner.stop_game()
        self.assertTrue(result["ok"])
        local_process.terminate.assert_called_once()
        local_process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
