import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gms_mcp.server.verification_policy import (
    clear_pending_compile_verification,
    current_verification_mode,
    decide_mutation_verification,
    flush_pending_compile_verification,
    get_pending_compile_verification,
    mark_compile_verification_pending,
)
from gms_helpers.transactions import (
    _compile_verification_process_pids,
    _terminate_compile_verification_processes,
    compile_verify_project,
)


class TestVerificationPolicy(unittest.TestCase):
    def test_default_mode_is_smart_when_env_is_absent(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
            os.environ.pop("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", None)

            self.assertEqual(current_verification_mode(), "smart")

    def test_explicit_off_keeps_post_mutation_compile_disabled(self):
        with patch.dict(os.environ, {"GMS_MCP_POST_MUTATION_VERIFY": "off"}, clear=False):
            decision = decide_mutation_verification("gm_create_script")

        self.assertEqual(decision.mode, "off")
        self.assertEqual(decision.action, "skip")

    def test_smart_mode_compiles_high_risk_and_defers_batchable_tools(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
            os.environ.pop("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", None)

            high_risk = decide_mutation_verification("gm_create_script")
            batchable = decide_mutation_verification("gm_sprite_add_frame")

        self.assertEqual(high_risk.mode, "smart")
        self.assertEqual(high_risk.action, "compile")
        self.assertEqual(batchable.mode, "smart")
        self.assertEqual(batchable.action, "defer")

    def test_pending_compile_state_round_trips_and_clears(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            decision = decide_mutation_verification("gm_sprite_add_frame")
            pending = mark_compile_verification_pending(
                root,
                tool_name="gm_sprite_add_frame",
                decision=decision,
                transaction={"changes": {"changed_count": 2}},
            )

            self.assertEqual(pending["operation_count"], 1)
            self.assertTrue(get_pending_compile_verification(root)["required"])

            cleared = clear_pending_compile_verification(root)

            self.assertEqual(cleared["operation_count"], 1)
            self.assertIsNone(get_pending_compile_verification(root))

    def test_flush_skips_when_no_pending_marker_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            result = flush_pending_compile_verification(root)

        self.assertTrue(result["ok"])
        self.assertFalse(result["compiled"])

    def test_compile_verify_accepts_completed_compile_stage_by_default(self):
        completed = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout="Final Compile finished.\nSaving IFF file... game.ios\nIgor complete.\nrunner failed later",
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.subprocess.run", return_value=completed),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertTrue(result["ok"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertTrue(result["accepted_compile_stage_success"])
        self.assertEqual(result["exit_code"], 1)

    def test_compile_verify_can_require_process_success(self):
        completed = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout="Final Compile finished.\nSaving IFF file... game.ios\nIgor complete.\nrunner failed later",
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {"GMS_MCP_POST_MUTATION_ACCEPT_COMPILE_STAGE_SUCCESS": "off"}, clear=False),
            patch("gms_helpers.transactions.subprocess.run", return_value=completed),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertFalse(result["accepted_compile_stage_success"])

    def test_compile_verify_timeout_fails_cleanly_and_cleans_new_helpers(self):
        timeout = subprocess.TimeoutExpired(
            cmd=["gms"],
            timeout=5,
            output="compile still running",
            stderr="",
        )
        cleanup = {"terminated_pids": [101, 102], "failed_pids": []}

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions._compile_verification_process_pids", return_value={10}),
            patch(
                "gms_helpers.transactions._terminate_compile_verification_processes",
                return_value=cleanup,
            ) as terminate_mock,
            patch("gms_helpers.transactions.subprocess.run", side_effect=timeout),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=5)

        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["timeout_cleanup"], cleanup)
        terminate_mock.assert_called_once()

    def test_compile_verify_holds_parent_machine_lock_through_timeout_cleanup(self):
        state = {"active": False}

        class RecordingLock:
            def __init__(self, _operation, _project_root):
                pass

            def __enter__(self):
                state["active"] = True
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                state["active"] = False

            def delegation_environment(self, _operation):
                self.assert_active()
                return {"GMS_MCP_TEST_DELEGATION": "1"}

            @staticmethod
            def assert_active():
                if not state["active"]:
                    raise AssertionError("compile verification machine lock is not active")

        timeout = subprocess.TimeoutExpired(cmd=["gms"], timeout=1, output="", stderr="")

        def cleanup_while_locked(_root, _baseline):
            RecordingLock.assert_active()
            return {"terminated_pids": [], "failed_pids": []}

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.GameMakerMachineLock", RecordingLock),
            patch("gms_helpers.transactions._compile_verification_process_pids", return_value=set()),
            patch(
                "gms_helpers.transactions._terminate_compile_verification_processes",
                side_effect=cleanup_while_locked,
            ),
            patch("gms_helpers.transactions.subprocess.run", side_effect=timeout),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertFalse(state["active"])

    def test_compile_verify_timeout_can_accept_already_completed_compile_stage(self):
        timeout = subprocess.TimeoutExpired(
            cmd=["gms"],
            timeout=5,
            output="Final Compile finished.\nSaving IFF file... game.ios\nStats : GMA\n",
            stderr="runner did not stop",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions._compile_verification_process_pids", return_value=set()),
            patch(
                "gms_helpers.transactions._terminate_compile_verification_processes",
                return_value={"terminated_pids": [], "failed_pids": []},
            ),
            patch("gms_helpers.transactions.subprocess.run", side_effect=timeout),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=5)

        self.assertTrue(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertTrue(result["accepted_compile_stage_success"])

    @unittest.skipIf(os.name == "nt", "POSIX process scan regression")
    def test_timeout_cleanup_terminates_new_scoped_process_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(60)  # gms_helpers.gms",
                    str(root),
                ],
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 2
                while process.pid not in _compile_verification_process_pids(root) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertIn(process.pid, _compile_verification_process_pids(root))
                cleanup = _terminate_compile_verification_processes(root, set())
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        self.assertIn(process.pid, cleanup["terminated_pids"])

    def test_windows_process_scan_and_tree_cleanup_are_project_scoped(self):
        root = Path("C:/Projects/Exact Game")
        listing = json.dumps(
            [
                {
                    "ProcessId": 101,
                    "CommandLine": r'C:\Runtime\Igor.exe --project="C:\Projects\Exact Game\game.yyp"',
                },
                {
                    "ProcessId": 202,
                    "CommandLine": r'C:\Runtime\runner.exe "C:\Projects\Other Game\game.win"',
                },
                {
                    "ProcessId": 203,
                    "CommandLine": r'C:\Runtime\Igor.exe --project="C:\Projects\Exact Game Backup\game.yyp"',
                },
            ]
        )
        scanner = MagicMock()
        scanner.communicate.return_value = (listing, "")
        taskkill_result = subprocess.CompletedProcess(args=["taskkill"], returncode=0, stdout="", stderr="")

        with (
            patch("gms_helpers.transactions.os.name", "nt"),
            patch("gms_helpers.transactions.subprocess.Popen", return_value=scanner),
        ):
            self.assertEqual(_compile_verification_process_pids(root), {101})

        with (
            patch("gms_helpers.transactions.os.name", "nt"),
            patch("gms_helpers.transactions._compile_verification_process_pids", return_value={101, 303}),
            patch("gms_helpers.transactions.subprocess.run", return_value=taskkill_result) as taskkill,
        ):
            cleanup = _terminate_compile_verification_processes(root, {101})

        self.assertEqual(cleanup, {"terminated_pids": [303], "failed_pids": []})
        taskkill.assert_called_once_with(
            ["taskkill", "/PID", "303", "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_compile_verify_retries_pre_compile_access_violation_with_bounded_attempts(self):
        access_violation = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout="",
            stderr="System.AccessViolationException: unstable Igor runtime",
        )
        success = subprocess.CompletedProcess(
            args=["gms"],
            returncode=0,
            stdout="Final Compile finished.\nSaving IFF file... game.ios\nIgor complete.",
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.dict(os.environ, {}, clear=False),
            patch(
                "gms_helpers.transactions.subprocess.run",
                side_effect=[access_violation, access_violation, success],
            ) as run_mock,
        ):
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY_INFRA_ATTEMPTS", None)
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertTrue(result["ok"])
        self.assertEqual(run_mock.call_count, 3)
        self.assertEqual(result["attempt_count"], 3)
        self.assertEqual(result["attempt_limit"], 3)
        self.assertTrue(result["retried_infrastructure_failure"])
        self.assertTrue(result["attempts"][0]["retryable_infrastructure_failure"])
        self.assertTrue(result["attempts"][1]["retryable_infrastructure_failure"])
        self.assertFalse(result["attempts"][2]["retryable_infrastructure_failure"])

    def test_compile_verify_does_not_retry_genuine_compile_failure(self):
        compile_failure = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout="Compile Errors: object event has invalid syntax",
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.subprocess.run", return_value=compile_failure) as run_mock,
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertEqual(run_mock.call_count, 1)
        self.assertEqual(result["attempt_count"], 1)
        self.assertFalse(result["retried_infrastructure_failure"])

    def test_compile_verify_does_not_retry_post_compile_access_violation(self):
        post_compile_crash = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout=(
                "Final Compile finished.\nSaving IFF file... game.ios\nStats : GMA\nSystem.AccessViolationException"
            ),
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.subprocess.run", return_value=post_compile_crash) as run_mock,
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertTrue(result["ok"])
        self.assertEqual(run_mock.call_count, 1)
        self.assertEqual(result["attempt_count"], 1)
        self.assertTrue(result["compile_stage_ok"])
        self.assertFalse(result["attempts"][0]["retryable_infrastructure_failure"])

    def test_compile_verify_accepts_gma_stats_when_lts_runner_crashes_after_compile(self):
        completed = subprocess.CompletedProcess(
            args=["gms"],
            returncode=-6,
            stdout="Final Compile finished.\nSaving IFF file... game.ios\nStats : GMA : Elapsed=82.776\n",
            stderr="post-compile runner crash",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.subprocess.run", return_value=completed),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertTrue(result["ok"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertTrue(result["accepted_compile_stage_success"])
        self.assertTrue(result["post_compile_exit_failure"])
