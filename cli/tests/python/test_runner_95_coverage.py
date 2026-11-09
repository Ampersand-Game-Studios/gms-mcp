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
from gms_helpers.runner_support.macos import MacOSProcess


class TestRunner95Coverage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "TestGame.yyp").write_text('{"resources": []}', encoding="utf-8")
        self.runner = GameMakerRunner(self.project_root)
        self._igor_idle_patch = patch.object(GameMakerRunner, "_wait_for_igor_idle")
        self._igor_idle_patch.start()
        self.addCleanup(self._igor_idle_patch.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prefabs_license_and_launch_target_remaining_paths(self):
        with patch("gms_helpers.runner_support.discovery.platform.system", return_value="Windows"):
            with patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(self.runner.get_prefabs_path())

        with patch("gms_helpers.runner_support.discovery.platform.system", return_value="Linux"):
            with patch.dict(os.environ, {}, clear=True):
                with patch("gms_helpers.runner_support.discovery.Path.home", return_value=self.project_root / "home"):
                    self.assertIsNone(self.runner.get_prefabs_path())

        with patch("gms_helpers.runner_support.discovery.platform.system", return_value="Windows"):
            with patch.dict(os.environ, {"USERNAME": "tester"}, clear=True):
                with patch(
                    "gms_helpers.runner_support.discovery.Path.home", return_value=self.project_root / "missing-home"
                ):
                    self.assertIsNone(self.runner.find_license_file())

        linux_home = self.project_root / "linux-home"
        base_dir = linux_home / ".config" / "GameMakerStudio2"
        base_dir.mkdir(parents=True)
        direct_license = base_dir / "license.plist"
        direct_license.write_text("<plist/>", encoding="utf-8")
        with patch("gms_helpers.runner_support.discovery.platform.system", return_value="Linux"):
            with patch("gms_helpers.runner_support.discovery.Path.home", return_value=linux_home):
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
        with patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 0.1, 2.0]):
            with patch("gms_helpers.runner_support.macos.time.sleep"):
                self.assertFalse(self.runner._wait_for_macos_main_loop(process, missing_log, 0, timeout_seconds=1.0))

        bad_log = self.project_root / "debug.log"
        bad_log.write_text("ignored", encoding="utf-8")
        process = MagicMock()
        process.poll.side_effect = [None, 1]
        with patch.object(Path, "open", side_effect=OSError("bad log")):
            with patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 0.1, 2.0]):
                with patch("gms_helpers.runner_support.macos.time.sleep"):
                    self.assertFalse(self.runner._wait_for_macos_main_loop(process, bad_log, 0, timeout_seconds=1.0))

        process = MagicMock()
        process.pid = 99
        process.poll.return_value = 1
        with patch.object(self.runner, "_find_macos_owned_helper_pids", return_value=(set(), set(), {})):
            with patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 2.0]):
                with patch("gms_helpers.runner_support.macos.time.sleep"):
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
        with (
            patch("gms_helpers.runner_support.macos.platform.system", return_value="Darwin"),
            patch("gms_helpers.runner_support.macos.subprocess.run", return_value=SimpleNamespace(stdout=ps_output)),
        ):
            processes = self.runner._snapshot_macos_processes()
        self.assertIn(str(game_path), processes[101].command)

        with patch("gms_helpers.runner_support.macos.os.kill", side_effect=RuntimeError("blocked")):
            self.runner._terminate_pid(10, "runner")

        kill_calls = []
        expected_signal = getattr(__import__("signal"), "SIGKILL", __import__("signal").SIGTERM)

        def stubborn_kill(pid, sig):
            kill_calls.append(sig)
            if sig == 0:
                return None
            if sig == expected_signal:
                raise RuntimeError("cannot kill")

        with patch("gms_helpers.runner_support.macos.os.kill", side_effect=stubborn_kill):
            with patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 0.1, 6.0]):
                with patch("gms_helpers.runner_support.macos.time.sleep"):
                    self.runner._terminate_pid(20, "runner")
        self.assertIn(expected_signal, kill_calls)

    def test_stop_macos_session_remaining_paths(self):
        runner_command = "/tmp/YoYo Runner.app/Contents/MacOS/Mac_Runner -game /tmp/game.ios"
        tail_command = "tail -F /tmp/debug.log"
        session = SimpleNamespace(
            run_id="run-10",
            pid=10,
            exe_path="/tmp/game.ios",
            log_file="/tmp/debug.log",
            runtime_type="VM",
            macos_runner_commands={"10": runner_command},
            macos_tail_commands={"20": tail_command},
            macos_runner_starts={"10": "start-10"},
            macos_tail_starts={"20": "start-20"},
        )
        processes = {
            10: MacOSProcess(10, 1, runner_command, "start-10"),
            20: MacOSProcess(20, 1, tail_command, "start-20"),
        }
        with patch.object(self.runner, "_snapshot_macos_processes", side_effect=[processes, {}, {}]):
            with patch.object(self.runner, "_stop_platform_process", return_value=True):
                with patch.object(self.runner._session_manager, "is_process_alive", return_value=False):
                    with patch.object(self.runner._session_manager, "clear_session") as mock_clear:
                        with patch(
                            "gms_helpers.runner_support.macos.time.monotonic",
                            side_effect=[0.0, 0.0, 0.0, 2.0, 2.0],
                        ):
                            with patch("gms_helpers.runner_support.macos.time.sleep"):
                                result = self.runner._stop_macos_run_session(session)
        self.assertTrue(result["ok"])
        mock_clear.assert_called_once()

        with patch.object(self.runner, "_snapshot_macos_processes", return_value=processes):
            with patch.object(self.runner, "_stop_platform_process", return_value=False):
                with patch.object(
                    self.runner._session_manager,
                    "is_process_alive",
                    return_value=True,
                ):
                    with patch.object(self.runner, "_terminate_pid"):
                        with patch.object(self.runner._session_manager, "clear_session"):
                            with patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 6.0]):
                                result = self.runner._stop_macos_run_session(session)
        self.assertFalse(result["ok"])
        self.assertIn("still alive", result["message"])

        call_counter = {"count": 0}

        def cleanup_alive(pid):
            call_counter["count"] += 1
            return call_counter["count"] <= 3

        with patch.object(self.runner, "_snapshot_macos_processes", side_effect=[processes, {}, {}]):
            with patch.object(self.runner, "_stop_platform_process", return_value=False):
                with patch.object(
                    self.runner._session_manager,
                    "is_process_alive",
                    side_effect=cleanup_alive,
                ):
                    with patch.object(self.runner, "_terminate_pid"):
                        with patch.object(self.runner._session_manager, "clear_session"):
                            with patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 6.0]):
                                result = self.runner._stop_macos_run_session(session)
        self.assertTrue(result["ok"])
        self.assertIn("manual cleanup", result["message"])

    def test_compile_project_remaining_paths(self):
        from gms_helpers.snapshot_build import BuildResult

        work = self.project_root / "snapshot-work"
        work.mkdir()
        with patch(
            "gms_helpers.snapshot_build.snapshot_compile",
            return_value=(
                {"ok": False, "message": "compile failed"},
                BuildResult(False, "BUILD_FAILED"),
                work,
                None,
            ),
        ):
            self.assertFalse(self.runner.compile_project(platform_target="macOS"))
        self.assertEqual(self.runner.last_failure_message, "compile failed")
        self.assertFalse(work.exists())
        with patch("gms_helpers.snapshot_build.snapshot_compile", side_effect=RuntimeError("build error")):
            self.assertFalse(self.runner.compile_project(platform_target="macOS"))
        self.assertIn("build error", self.runner.last_failure_message)
        with patch.object(self.runner, "_build_platform_action_command", side_effect=RuntimeError("boom")):
            self.assertFalse(self.runner.compile_project(platform_target="Windows"))

    def test_ide_temp_run_remaining_paths(self):
        temp_root = self.project_root / "tmp"
        session = SimpleNamespace(run_id="run-1")

        launch_path = temp_root / "TestGame.exe"
        launch_path.parent.mkdir(parents=True, exist_ok=True)
        launch_path.write_text("bin")
        with patch.object(self.runner, "run_project_direct", return_value={"ok": True}) as owned:
            self.assertTrue(self.runner._run_project_ide_temp_approach(platform_target="macOS", background=True)["ok"])
        owned.assert_called_once_with("macOS", "VM", True, "temp")

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
                                    with patch.object(
                                        self.runner._session_manager, "create_session", return_value=session
                                    ):
                                        with patch.object(self.runner._session_manager, "clear_session"):
                                            self.assertFalse(
                                                self.runner._run_project_ide_temp_approach(
                                                    platform_target="Windows", background=False
                                                )
                                            )

        with patch.object(self.runner, "_run_igor_command", side_effect=RuntimeError("explode")):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_system_temp_root", return_value=temp_root):
                    with patch.object(
                        self.runner, "_build_platform_action_command", return_value=["igor", "PackageZip"]
                    ):
                        self.assertFalse(self.runner._run_project_ide_temp_approach(platform_target="Windows"))

    def test_classic_run_and_stop_game_remaining_paths(self):
        temp_root = self.project_root / "tmp"

        with patch.object(
            self.runner, "run_project_direct", return_value={"ok": False, "message": "owned failure"}
        ) as owned:
            result = self.runner._run_project_classic_approach(platform_target="macOS", background=True)
        self.assertFalse(result["ok"])
        owned.assert_called_once_with("macOS", "VM", True, "project")

        fg_process = MagicMock()
        fg_process.pid = 444
        fg_process.stdout = iter(["error line\n", "warning line\n", "compile line\n", "plain line\n"])
        fg_process.returncode = 4
        fg_process.wait.return_value = 4
        with patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]):
            with patch.object(self.runner, "find_project_file", return_value=self.project_root / "TestGame.yyp"):
                with patch.object(self.runner, "_run_igor_command", return_value=fg_process):
                    with patch.object(
                        self.runner._session_manager, "create_session", return_value=SimpleNamespace(run_id="run-2")
                    ):
                        with patch.object(self.runner._session_manager, "clear_session"):
                            self.assertFalse(
                                self.runner._run_project_classic_approach(platform_target="Windows", background=False)
                            )

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


class TestRunnerSafetyFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / "TestGame.yyp").write_text('{"resources": []}', encoding="utf-8")
        self.runner = GameMakerRunner(self.project_root)
        for name in ("_wait_for_igor_idle",):
            patcher = patch.object(GameMakerRunner, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _game(self, pid=os.getpid()):
        game = MagicMock()
        game.pid = pid
        game.wait.side_effect = lambda *a, **k: None
        return game

    def test_project_lease_refuses_a_second_run_of_the_same_project(self):
        from gms_helpers.mac_runtime import project_run_lock

        held = project_run_lock(self.project_root)
        held.acquire()
        self.addCleanup(held.release)
        with (
            patch("gms_helpers.runner_support.execution._PROJECT_LEASE_TIMEOUT_SECONDS", 0.0),
            patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]),
            patch.object(self.runner, "_run_igor_command") as launch,
        ):
            self.assertFalse(self.runner._run_project_classic_approach("Windows", background=True))
        launch.assert_not_called()
        self.assertIn("lock", self.runner.last_failure_message)

    def test_background_classic_run_logs_igor_output_and_keeps_its_lease(self):
        from gms_helpers.mac_runtime import project_run_lock

        game = self._game()
        released = []
        with (
            patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]),
            patch.object(self.runner, "_run_igor_command", return_value=game) as launch,
            patch.object(self.runner, "_hold_lease_until_exit", side_effect=lambda p, lease: released.append(lease)),
        ):
            result = self.runner._run_project_classic_approach("Windows", background=True)
        self.assertTrue(result["ok"])
        log_file = launch.call_args.kwargs["output_file"]
        self.assertEqual(str(log_file), result["log_file"])
        self.assertEqual(self.runner._session_manager.get_current_session().log_file, str(log_file))
        # The lease stays held for the running game; a second launcher cannot take it.
        self.assertFalse(project_run_lock(self.project_root).try_acquire())
        released[0].release()

    def test_retry_reset_runs_under_the_machine_lock(self):
        events = []

        class _Lock:
            def __init__(self, operation, _root):
                self.operation = operation

            def __enter__(self):
                events.append(("lock", self.operation))

            def __exit__(self, *_exc):
                events.append(("unlock", self.operation))

        def attempt(*_args):
            self.runner.last_failure_retryable = len(events) == 0
            return False

        with (
            patch("gms_helpers.runner_support.execution.GameMakerMachineLock", _Lock),
            patch.object(self.runner, "_run_project_classic_approach", side_effect=attempt),
            patch.object(
                self.runner, "_reset_igor_transient_state", side_effect=lambda: events.append(("reset", None))
            ),
        ):
            self.runner.run_project_direct("Windows", output_location="project")
        self.assertEqual(events[:3], [("lock", "run-retry-reset"), ("reset", None), ("unlock", "run-retry-reset")])

    def test_igor_is_stopped_when_reading_its_output_fails(self):
        process = MagicMock()
        process.poll.return_value = None

        def lines():
            yield "ok\n"
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte")

        process.stdout = lines()
        with self.assertRaises(UnicodeDecodeError):
            self.runner._stream_igor_output(process, "local run")
        process.terminate.assert_called_once()

    def test_igor_pipe_decodes_utf8_with_replacement(self):
        with patch("gms_helpers.runner_process.subprocess.Popen", return_value=SimpleNamespace(pid=1)) as popen:
            self.runner._run_igor_command(["/fake/Igor"])
        self.assertEqual(popen.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(popen.call_args.kwargs["errors"], "replace")

    def test_licence_choice_across_accounts_is_the_newest_and_reported(self):
        base = self.project_root / "home" / ".config" / "GameMakerStudio2"
        older = base / "alice_1" / "licence.plist"
        newer = base / "bob_2" / "licence.plist"
        for path, mtime in ((older, 1_000_000), (newer, 2_000_000)):
            path.parent.mkdir(parents=True)
            path.write_text("licence")
            os.utime(path, (mtime, mtime))
        output = []
        with (
            patch("gms_helpers.runner_support.discovery.platform.system", return_value="Linux"),
            patch("gms_helpers.runner_support.discovery.Path.home", return_value=self.project_root / "home"),
            patch.dict(os.environ, {}, clear=True),
            patch("builtins.print", side_effect=lambda *a, **k: output.append(" ".join(map(str, a)))),
        ):
            self.assertEqual(self.runner.find_license_file(), newer)
        self.assertTrue(any("2 accounts" in line and str(newer) in line for line in output))


if __name__ == "__main__":
    unittest.main()
