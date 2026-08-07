#!/usr/bin/env python3
"""Focused regressions for macOS Igor overlap and runner ownership."""

from __future__ import annotations

import subprocess
import platform
import sys
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.runner import GameMakerRunner
from gms_helpers.runner_process import run_igor_command
from gms_helpers.runner_support.macos import MacOSProcess
from gms_mcp.server.macos_runner_timeout import cleanup_macos_ownership_manifest


class TestMacOSRunnerOwnership(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name).resolve()
        (self.project_root / "TestGame.yyp").write_text('{"resources": []}', encoding="utf-8")
        self.runner = GameMakerRunner(self.project_root)
        self.game_path = self.project_root / "output" / "TestGame" / "game.ios"
        self.debug_log = self.project_root / "output" / "TestGame" / "debug.log"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_existing_ide_igor_blocks_owned_launch(self) -> None:
        active = {41: MacOSProcess(41, 9, "/runtime/Igor")}
        with (
            patch("gms_helpers.runner_support.macos.platform.system", return_value="Darwin"),
            patch.object(self.runner, "_find_active_igor_processes", return_value=active),
        ):
            with self.assertRaisesRegex(RuntimeError, r"PID\(s\): \[41\].*Refusing to overlap"):
                self.runner._wait_for_igor_idle(timeout_seconds=0)

    def test_owned_launch_waits_until_ide_igor_finishes(self) -> None:
        active = {41: MacOSProcess(41, 9, "/runtime/Igor")}
        with (
            patch("gms_helpers.runner_support.macos.platform.system", return_value="Darwin"),
            patch.object(self.runner, "_find_active_igor_processes", side_effect=[active, {}]),
            patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 0.0, 0.0]),
            patch("gms_helpers.runner_support.macos.time.sleep") as sleep,
        ):
            self.runner._wait_for_igor_idle(timeout_seconds=1)
        sleep.assert_called_once()

    def test_post_launch_foreign_igor_race_is_rejected(self) -> None:
        active = {
            77: MacOSProcess(77, 1, "/runtime/Igor"),
            88: MacOSProcess(88, 9, "/ide/runtime/Igor"),
        }
        with patch.object(self.runner, "_find_active_igor_processes", return_value=active):
            with self.assertRaisesRegex(RuntimeError, r"PID\(s\): \[88\].*Aborting"):
                self.runner._reject_foreign_igor_after_launch(77)

    def test_runner_option_parser_preserves_windows_path_backslashes(self) -> None:
        command = r'/runtime/Mac_Runner -game "C:\Users\runner admin\output\game.ios"'

        game_path = self.runner._macos_runner_game_path(command)

        self.assertIsNotNone(game_path)
        self.assertEqual(str(game_path), r"C:\Users\runner admin\output\game.ios")

    def test_process_launch_token_requires_exact_environment_marker(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout="/runtime/Mac_Runner GMS_MCP_MACOS_LAUNCH_TOKEN=owned-token OTHER=value\n",
        )
        with (
            patch("gms_helpers.runner_support.macos.platform.system", return_value="Darwin"),
            patch("gms_helpers.runner_support.macos.subprocess.run", return_value=completed),
        ):
            self.assertTrue(self.runner._macos_process_has_launch_token(21, "owned-token"))
            self.assertFalse(self.runner._macos_process_has_launch_token(21, "other-token"))

    @unittest.skipUnless(platform.system() == "Darwin", "LaunchServices inheritance is macOS-specific")
    def test_launchservices_preserves_ownership_marker(self) -> None:
        bundle = self.project_root / "Marker.app"
        contents = bundle / "Contents"
        executable = contents / "MacOS" / "marker"
        result_path = self.project_root / "marker-result"
        executable.parent.mkdir(parents=True)
        (contents / "Info.plist").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>marker</string>
<key>CFBundleIdentifier</key><string>com.ampersand-gms-mcp.test-launch-marker</string>
<key>CFBundleName</key><string>GMS MCP Test Marker</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSBackgroundOnly</key><true/>
</dict></plist>
""",
            encoding="utf-8",
        )
        source = contents / "marker.c"
        source.write_text(
            "#include <stdio.h>\n#include <stdlib.h>\n#include <unistd.h>\n"
            'int main(void) { FILE *f = fopen("' + str(result_path) + '", "w"); fprintf(f, "%d %s\\n", getpid(), '
            'getenv("GMS_MCP_MACOS_LAUNCH_TOKEN")); fclose(f); sleep(2); return 0; }\n',
            encoding="utf-8",
        )
        subprocess.run(["/usr/bin/clang", str(source), "-o", str(executable)], check=True)
        environment = dict(__import__("os").environ)
        environment["GMS_MCP_MACOS_LAUNCH_TOKEN"] = "launchservices-owned-token"
        subprocess.run(["/usr/bin/open", "-n", str(bundle)], check=True, env=environment)
        for _ in range(20):
            if result_path.exists():
                break
            __import__("time").sleep(0.1)
        pid_text, inherited_token = result_path.read_text(encoding="utf-8").strip().split()
        self.assertEqual(inherited_token, "launchservices-owned-token")
        self.assertTrue(self.runner._macos_process_has_launch_token(int(pid_text), inherited_token))

    def test_classic_run_does_not_start_igor_when_overlap_guard_fails(self) -> None:
        with (
            patch.object(self.runner, "_wait_for_igor_idle", side_effect=RuntimeError("busy")),
            patch.object(self.runner, "_run_igor_command") as launch,
        ):
            self.assertFalse(self.runner._run_project_classic_approach("macOS", background=False))
        launch.assert_not_called()
        self.assertEqual(self.runner.last_failure_message, "busy")

    def test_only_token_marked_bare_and_owned_temp_runners_are_owned(self) -> None:
        expected = f"/runtime/Mac_Runner -game {self.game_path}"
        scoped_temp_game = Path("/tmp/gms-mcp/abc/temp/TestGame_A1B2_VM/game.ios")
        bare = f"{Path.home()}/GameMakerStudio2/GM_MAC/TestGame/YoYo Runner.app/Contents/MacOS/Mac_Runner"
        unrelated = f"{Path.home()}/GameMakerStudio2/GM_MAC/OtherGame/YoYo Runner.app/Contents/MacOS/Mac_Runner"
        preexisting = f"/runtime/Mac_Runner -game {self.game_path}"
        processes = {
            10: MacOSProcess(10, 1, preexisting),
            20: MacOSProcess(20, 77, expected),
            21: MacOSProcess(21, 1, bare),
            22: MacOSProcess(22, 1, unrelated),
            23: MacOSProcess(23, 1, f"/runtime/Mac_Runner -game {scoped_temp_game}"),
            30: MacOSProcess(30, 77, f"tail -F {self.debug_log}"),
        }
        with (
            patch.object(self.runner, "_snapshot_macos_processes", return_value=processes),
            patch.object(
                self.runner,
                "_owned_macos_temp_root",
                return_value=Path("/tmp/gms-mcp/abc/temp").resolve(strict=False),
            ),
            patch.object(
                self.runner,
                "_macos_process_has_launch_token",
                side_effect=lambda pid, _token: pid in {20, 21, 23, 30},
            ),
        ):
            runner_pids, tail_pids, _snapshot = self.runner._find_macos_owned_helper_pids(
                self.game_path,
                self.debug_log,
                baseline_runner_pids={10},
                baseline_tail_pids=set(),
                owned_igor_pid=77,
                launch_token="owned-token",
            )
        self.assertEqual(runner_pids, {20, 21, 23})
        self.assertEqual(tail_pids, {30})

    def test_timeout_cleanup_kills_new_bare_but_preserves_preexisting_and_unrelated(self) -> None:
        owned = {
            21: MacOSProcess(
                21,
                1,
                f"{Path.home()}/GameMakerStudio2/GM_MAC/TestGame/YoYo Runner.app/Contents/MacOS/Mac_Runner",
                "Fri Aug 7 14:00:00 2026",
            ),
            30: MacOSProcess(30, 77, f"tail -F {self.debug_log}", "Fri Aug 7 14:00:01 2026"),
        }
        with (
            patch.object(self.runner, "_find_macos_owned_helper_pids", return_value=({21}, {30}, owned)),
            patch.object(self.runner, "_snapshot_macos_processes", return_value=owned),
            patch.object(self.runner, "_terminate_pid") as terminate,
        ):
            self.runner._cleanup_macos_validation_helpers(
                self.game_path,
                self.debug_log,
                baseline_runner_pids={10},
                baseline_tail_pids={11},
                owned_igor_pid=77,
            )
        self.assertEqual({call.args[0] for call in terminate.call_args_list}, {21, 30})

    def test_success_cleanup_sweep_catches_late_launchservices_bare_runner(self) -> None:
        bare = MacOSProcess(
            21,
            1,
            f"{Path.home()}/GameMakerStudio2/GM_MAC/TestGame/YoYo Runner.app/Contents/MacOS/Mac_Runner",
            "late-start",
        )
        with (
            patch.object(self.runner, "_snapshot_macos_processes", side_effect=[{}, {21: bare}, {21: bare}]),
            patch.object(self.runner, "_macos_process_has_launch_token", return_value=True),
            patch.object(self.runner, "_terminate_pid") as terminate,
            patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 1.0, 4.0]),
            patch("gms_helpers.runner_support.macos.time.sleep"),
        ):
            self.runner._cleanup_macos_validation_helpers(
                self.game_path,
                self.debug_log,
                {},
                {},
                launch_token="owned-token",
                sweep_seconds=3.0,
            )
        terminate.assert_called_once_with(21, "runner", bare)

    def test_runner_start_tracks_bare_and_expected_but_uses_expected_as_primary(self) -> None:
        process = MagicMock(pid=77)
        expected = MacOSProcess(20, 77, f"/runtime/Mac_Runner -game {self.game_path}")
        bare = MacOSProcess(
            21,
            1,
            f"{Path.home()}/GameMakerStudio2/GM_MAC/TestGame/YoYo Runner.app/Contents/MacOS/Mac_Runner",
        )
        with patch.object(
            self.runner,
            "_find_macos_owned_helper_pids",
            return_value=({20, 21}, {30}, {20: expected, 21: bare}),
        ):
            pid, runners, tails = self.runner._wait_for_macos_runner_start(
                process,
                self.game_path,
                self.debug_log,
                set(),
                set(),
                timeout_seconds=1,
            )
        self.assertEqual(pid, 20)
        self.assertEqual(runners, {20, 21})
        self.assertEqual(tails, {30})

    def test_session_token_finds_bare_runner_spawned_after_initial_tracking(self) -> None:
        bare = MacOSProcess(
            21,
            1,
            f"{Path.home()}/GameMakerStudio2/GM_MAC/TestGame/YoYo Runner.app/Contents/MacOS/Mac_Runner",
        )
        session = SimpleNamespace(
            macos_runner_commands={},
            macos_tail_commands={},
            macos_runner_starts={},
            macos_tail_starts={},
            macos_launch_token="owned-token",
        )
        with patch.object(self.runner, "_macos_process_has_launch_token", return_value=True):
            runners, tails = self.runner._tracked_macos_helper_pids(session, {21: bare})
        self.assertEqual(runners, {21})
        self.assertEqual(tails, set())

    def test_same_project_user_bare_runner_without_token_is_never_owned(self) -> None:
        bare = MacOSProcess(
            21,
            1,
            f"{Path.home()}/GameMakerStudio2/GM_MAC/TestGame/YoYo Runner.app/Contents/MacOS/Mac_Runner",
        )
        with (
            patch.object(self.runner, "_snapshot_macos_processes", return_value={21: bare}),
            patch.object(self.runner, "_macos_process_has_launch_token", return_value=False),
        ):
            runners, tails, _ = self.runner._find_macos_owned_helper_pids(
                self.game_path,
                self.debug_log,
                set(),
                set(),
                owned_igor_pid=None,
                launch_token="owned-token",
            )
        self.assertEqual(runners, set())
        self.assertEqual(tails, set())

    def test_recycled_baseline_pid_does_not_hide_new_owned_runner(self) -> None:
        old = MacOSProcess(21, 1, "/runtime/Mac_Runner -game /old/game.ios", "old-start")
        new = MacOSProcess(21, 1, "/runtime/Mac_Runner -game /new/game.ios", "new-start")
        with (
            patch.object(self.runner, "_snapshot_macos_processes", return_value={21: new}),
            patch.object(self.runner, "_macos_process_has_launch_token", return_value=True),
        ):
            runners, _tails, _ = self.runner._find_macos_owned_helper_pids(
                self.game_path,
                self.debug_log,
                {21: old},
                {},
                owned_igor_pid=None,
                launch_token="owned-token",
            )
        self.assertEqual(runners, {21})

    def test_manifest_records_launch_boundary_and_parent_reuses_exact_baseline(self) -> None:
        manifest_path = self.project_root / "ownership.json"
        baseline = {
            10: MacOSProcess(10, 1, f"/runtime/Mac_Runner -game {self.game_path}", "start-10"),
            11: MacOSProcess(11, 10, f"tail -F {self.debug_log}", "start-11"),
        }
        temp_root = self.project_root / "igor" / "temp"
        with (
            patch.dict("os.environ", {"GMS_MCP_MACOS_OWNERSHIP_MANIFEST": str(manifest_path)}),
            patch.object(self.runner, "_owned_macos_temp_root", return_value=temp_root),
        ):
            self.runner._write_macos_ownership_manifest(baseline, self.game_path, self.debug_log)

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["baseline"]["10"]["started"], "start-10")
        self.assertEqual(payload["owned_temp_root"], str(temp_root))

        with (
            patch("gms_helpers.runner.GameMakerRunner", return_value=self.runner),
            patch.object(self.runner, "_cleanup_macos_validation_helpers") as cleanup,
            patch("gms_mcp.server.macos_runner_timeout.time.monotonic", side_effect=[0.0, 4.0]),
        ):
            cleanup_macos_ownership_manifest(manifest_path)
        cleanup.assert_called_once_with(
            self.game_path,
            self.debug_log,
            {10: baseline[10]},
            {11: baseline[11]},
            None,
            None,
            None,
            None,
        )
        self.assertEqual(self.runner._macos_timeout_temp_root_override, temp_root)

    def test_successful_foreground_run_keeps_behavior_and_runs_owned_cleanup(self) -> None:
        process = MagicMock(pid=77, returncode=0)
        process.poll.return_value = None
        process.wait.return_value = 0
        owned_processes = {
            20: MacOSProcess(20, 77, f"/runtime/Mac_Runner -game {self.game_path}"),
            21: MacOSProcess(
                21,
                1,
                f"{Path.home()}/GameMakerStudio2/GM_MAC/TestGame/YoYo Runner.app/Contents/MacOS/Mac_Runner",
            ),
        }
        with (
            patch.object(self.runner, "_wait_for_igor_idle") as wait_for_idle,
            patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]),
            patch.object(self.runner, "_snapshot_macos_processes", side_effect=[{}, owned_processes, owned_processes]),
            patch.object(self.runner, "_run_igor_command", return_value=process) as launch,
            patch.object(self.runner, "_reject_foreign_igor_after_launch"),
            patch.object(self.runner, "_collect_igor_output_async", return_value=([], MagicMock())),
            patch.object(self.runner, "_wait_for_macos_runner_start", return_value=(20, {20, 21}, set())),
            patch.object(self.runner, "_cleanup_macos_validation_helpers") as cleanup,
        ):
            self.assertTrue(self.runner._run_project_classic_approach("macOS", background=False))
        cleanup.assert_called_once_with(
            self.game_path,
            self.debug_log,
            {},
            {},
            77,
            None,
            None,
            ANY,
            sweep_seconds=3.0,
        )
        launch_kwargs = launch.call_args.kwargs
        self.assertIn("GMS_MCP_MACOS_LAUNCH_TOKEN", launch_kwargs["environment_overrides"])
        self.assertEqual(wait_for_idle.call_count, 2)
        self.assertIsNone(self.runner._session_manager.get_current_session())

    def test_signal_revalidation_allows_reparenting_but_rejects_pid_reuse(self) -> None:
        expected = MacOSProcess(20, 77, "/runtime/Mac_Runner -game /tmp/game.ios", "start-20")
        reparented = MacOSProcess(20, 1, expected.command, expected.started)
        with (
            patch.object(self.runner, "_snapshot_macos_processes", side_effect=[{20: reparented}, {}]),
            patch("gms_helpers.runner_support.macos.os.kill") as kill,
        ):
            self.runner._terminate_pid(20, "runner", expected)
        kill.assert_called_once_with(20, __import__("signal").SIGTERM)

        recycled = MacOSProcess(20, 1, expected.command, "later-start")
        with (
            patch.object(self.runner, "_snapshot_macos_processes", return_value={20: recycled}),
            patch("gms_helpers.runner_support.macos.os.kill") as kill,
        ):
            self.runner._terminate_pid(20, "runner", expected)
        kill.assert_not_called()

    def test_stop_revalidates_persisted_commands_and_ignores_pid_reuse(self) -> None:
        runner_command = f"/runtime/Mac_Runner -game {self.game_path}"
        session = SimpleNamespace(
            pid=20,
            exe_path=str(self.game_path),
            macos_runner_commands={"20": runner_command, "21": "old command"},
            macos_tail_commands={},
            macos_runner_starts={"20": "start-20", "21": "old-start"},
            macos_tail_starts={},
        )
        processes = {
            20: MacOSProcess(20, 1, runner_command, "start-20"),
            21: MacOSProcess(21, 1, "/usr/bin/unrelated", "new-start"),
        }
        runners, tails = self.runner._tracked_macos_helper_pids(session, processes)
        self.assertEqual(runners, {20})
        self.assertEqual(tails, set())

    def test_stale_session_does_not_issue_project_wide_stop_against_user_runner(self) -> None:
        user_command = f"/runtime/Mac_Runner -game {self.game_path}"
        stale_session = SimpleNamespace(
            pid=20,
            exe_path=str(self.game_path),
            log_file=str(self.debug_log),
            runtime_type="VM",
            macos_igor_pid=None,
            macos_igor_command=None,
            macos_runner_commands={},
            macos_tail_commands={},
        )
        with (
            patch.object(
                self.runner,
                "_snapshot_macos_processes",
                return_value={20: MacOSProcess(20, 1, user_command)},
            ),
            patch.object(self.runner, "_stop_platform_process") as stop,
            patch.object(self.runner._session_manager, "clear_session"),
        ):
            result = self.runner._stop_macos_run_session(stale_session)
        self.assertTrue(result["ok"])
        stop.assert_not_called()

    def test_exception_after_launch_cleans_exact_owned_igor(self) -> None:
        process = MagicMock(pid=77)
        igor = MacOSProcess(77, 1, "/runtime/Igor -- Mac Run")
        with (
            patch.object(self.runner, "_wait_for_igor_idle"),
            patch.object(self.runner, "_build_platform_action_command", return_value=["igor", "Run"]),
            patch.object(
                self.runner,
                "_snapshot_macos_processes",
                side_effect=[{}, {77: igor}],
            ),
            patch.object(self.runner, "_run_igor_command", return_value=process),
            patch.object(self.runner, "_reject_foreign_igor_after_launch"),
            patch.object(self.runner, "_collect_igor_output_async", side_effect=RuntimeError("reader failed")),
            patch.object(self.runner, "_cleanup_macos_validation_helpers") as cleanup,
        ):
            self.assertFalse(self.runner._run_project_classic_approach("macOS", background=False))
        cleanup.assert_called_once_with(
            self.game_path,
            self.debug_log,
            {},
            {},
            77,
            igor.command,
            "",
            ANY,
            sweep_seconds=3.0,
        )

    def test_stop_terminates_only_persisted_owned_runner_and_igor(self) -> None:
        runner_command = f"/runtime/Mac_Runner -game {self.game_path}"
        igor_command = "/runtime/Igor -- Mac Run"
        session = SimpleNamespace(
            pid=20,
            exe_path=str(self.game_path),
            log_file=str(self.debug_log),
            runtime_type="VM",
            macos_igor_pid=77,
            macos_igor_command=igor_command,
            macos_igor_started="start-77",
            macos_runner_commands={"20": runner_command},
            macos_tail_commands={},
            macos_runner_starts={"20": "start-20"},
            macos_tail_starts={},
        )
        processes = {
            20: MacOSProcess(20, 1, runner_command, "start-20"),
            77: MacOSProcess(77, 1, igor_command, "start-77"),
        }
        terminated: set[int] = set()
        with (
            patch.object(self.runner, "_snapshot_macos_processes", side_effect=[processes, processes, {}]),
            patch.object(self.runner, "_stop_platform_process", return_value=False),
            patch.object(self.runner._session_manager, "is_process_alive", return_value=True),
            patch.object(self.runner._session_manager, "clear_session"),
            patch.object(
                self.runner, "_terminate_pid", side_effect=lambda pid, _label, _expected=None: terminated.add(pid)
            ),
            patch("gms_helpers.runner_support.macos.time.monotonic", side_effect=[0.0, 6.0]),
        ):
            result = self.runner._stop_macos_run_session(session)
        self.assertTrue(result["ok"])
        self.assertEqual(terminated, {20, 77})

    def test_igor_inherits_worker_process_group_for_outer_timeout_cleanup(self) -> None:
        with patch("gms_helpers.runner_process.subprocess.Popen", return_value=SimpleNamespace(pid=8)) as popen:
            run_igor_command(["/runtime/Igor"], cwd=self.project_root)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.project_root))
        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
