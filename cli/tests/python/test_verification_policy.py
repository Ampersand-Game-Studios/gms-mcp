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
    _run_compile_verification_child,
    _terminate_verification_child,
    compile_verify_project,
)

CHILD = "gms_helpers.transactions._run_compile_verification_child"


def _finished(completed):
    return completed, None


class TestVerificationPolicy(unittest.TestCase):
    def test_default_mode_is_smart_when_env_is_absent(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
            os.environ.pop("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", None)

            self.assertEqual(current_verification_mode(), "smart")

    def test_unrecognised_project_policy_verifies_in_smart_mode_and_reports_it(self):
        from gms_mcp.server.verification_policy import verification_mode_notice

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GMS_MCP_POST_MUTATION_VERIFY", None)
            os.environ.pop("GMS_MCP_VERIFY_COMPILE_AFTER_MUTATION", None)
            root = Path(temp_dir)
            (root / ".gms-mcp.json").write_text(json.dumps({"verification": {"post_mutation": "of"}}))

            decision = decide_mutation_verification("gm_create_script", root)
            notice = verification_mode_notice(root)

        self.assertEqual(decision.mode, "smart")
        self.assertEqual(decision.action, "compile")
        self.assertIn("verification.post_mutation", notice)
        self.assertIn(notice, decision.reason)

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
            patch(CHILD, return_value=_finished(completed)),
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
            patch(CHILD, return_value=_finished(completed)),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertFalse(result["accepted_compile_stage_success"])

    def test_compile_verify_timeout_fails_cleanly_and_reports_cleanup(self):
        cleanup = {"process_group": 100, "terminated_pids": [100, 101], "failed_pids": []}
        timed_out = subprocess.CompletedProcess(args=["gms"], returncode=-9, stdout="compile still running", stderr="")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(CHILD, return_value=(timed_out, cleanup)) as child,
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=5)

        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["timeout_cleanup"], cleanup)
        self.assertEqual(child.call_args.kwargs["timeout_seconds"], 5)

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

        def child_timing_out_while_locked(*_args, **_kwargs):
            RecordingLock.assert_active()
            return (
                subprocess.CompletedProcess(args=["gms"], returncode=-9, stdout="", stderr=""),
                {"terminated_pids": [], "failed_pids": []},
            )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.GameMakerMachineLock", RecordingLock),
            patch(CHILD, side_effect=child_timing_out_while_locked),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertFalse(state["active"])

    def test_compile_verify_timeout_can_accept_already_completed_compile_stage(self):
        timed_out = subprocess.CompletedProcess(
            args=["gms"],
            returncode=-9,
            stdout="Final Compile finished.\nSaving IFF file... game.ios\nStats : GMA\n",
            stderr="runner did not stop",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(CHILD, return_value=(timed_out, {"terminated_pids": [], "failed_pids": []})),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=5)

        self.assertTrue(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertTrue(result["accepted_compile_stage_success"])

    @unittest.skipIf(os.name == "nt", "POSIX process-group regression")
    def test_timeout_stops_the_child_group_and_spares_unrelated_project_processes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            marker = root / "grandchild.pid"
            # The user's own process naming the project and a helper marker must survive.
            bystander = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)  # tail -F gms_helpers.gms", str(root)],
                start_new_session=True,
            )
            child_code = (
                "import subprocess, sys, time; "
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                f"open({str(marker)!r}, 'w').write(str(g.pid)); "
                "print('compiling', flush=True); time.sleep(60)"
            )
            try:
                started = time.monotonic()
                completed, cleanup = _run_compile_verification_child(
                    [sys.executable, "-c", child_code], cwd=root, env=dict(os.environ), timeout_seconds=2
                )
                grandchild = int(marker.read_text())
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        os.kill(grandchild, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    self.fail("the verification child's own helper survived the timeout")
                self.assertIsNone(bystander.poll())
            finally:
                bystander.kill()
                bystander.wait(timeout=5)

        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(completed.returncode, -9)
        self.assertIn("compiling", completed.stdout)
        self.assertIsNotNone(cleanup)
        self.assertNotIn(bystander.pid, cleanup["terminated_pids"])

    def test_windows_timeout_cleanup_kills_only_the_child_tree(self):
        process = MagicMock(pid=303)
        process.poll.return_value = 0
        taskkill_result = subprocess.CompletedProcess(args=["taskkill"], returncode=0, stdout="", stderr="")

        with (
            patch("gms_helpers.transactions.os.name", "nt"),
            patch("gms_helpers.transactions.subprocess.run", return_value=taskkill_result) as taskkill,
        ):
            cleanup = _terminate_verification_child(process)

        self.assertEqual(cleanup, {"process_group": 303, "terminated_pids": [303], "failed_pids": []})
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
                CHILD,
                side_effect=[_finished(access_violation), _finished(access_violation), _finished(success)],
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

    def test_compile_verify_renews_single_use_lock_delegation_for_each_retry(self):
        issued_tokens: list[str] = []
        child_tokens: list[str] = []

        class RecordingLock:
            def __init__(self, _operation, _project_root):
                pass

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                pass

            def delegation_environment(self, operation):
                self.assertEqual(operation, "compile")
                token = f"delegation-{len(issued_tokens) + 1}"
                issued_tokens.append(token)
                return {"GMS_MCP_MACHINE_LOCK_DELEGATION_TOKEN": token}

            @staticmethod
            def assertEqual(actual, expected):
                if actual != expected:
                    raise AssertionError(f"{actual!r} != {expected!r}")

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

        def run_attempt(*_args, **kwargs):
            child_tokens.append(kwargs["env"]["GMS_MCP_MACHINE_LOCK_DELEGATION_TOKEN"])
            return _finished(access_violation if len(child_tokens) == 1 else success)

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("gms_helpers.transactions.GameMakerMachineLock", RecordingLock),
            patch(CHILD, side_effect=run_attempt),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertTrue(result["ok"])
        self.assertEqual(issued_tokens, ["delegation-1", "delegation-2"])
        self.assertEqual(child_tokens, issued_tokens)

    def test_compile_verify_does_not_retry_genuine_compile_failure(self):
        compile_failure = subprocess.CompletedProcess(
            args=["gms"],
            returncode=1,
            stdout="Compile Errors: object event has invalid syntax",
            stderr="",
        )

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch(CHILD, return_value=_finished(compile_failure)) as run_mock,
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
            patch(CHILD, return_value=_finished(post_compile_crash)) as run_mock,
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
            patch(CHILD, return_value=_finished(completed)),
        ):
            result = compile_verify_project(temp_dir, platform="macOS", runtime="VM", timeout_seconds=1)

        self.assertTrue(result["ok"])
        self.assertTrue(result["compile_stage_ok"])
        self.assertTrue(result["accepted_compile_stage_success"])
        self.assertTrue(result["post_compile_exit_failure"])
