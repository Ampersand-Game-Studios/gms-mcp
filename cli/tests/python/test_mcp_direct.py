#!/usr/bin/env python3
import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_mcp.server import dispatch as server
from gms_mcp.server import project as server_project
from gms_mcp.server.direct import _handler_reference, _run_direct, _run_direct_thread_shielded
from gms_mcp.server.direct_worker import _capture_output
from gms_mcp.server.dry_run_policy import _requires_dry_run_for_tool
from gms_mcp.server.results import ToolRunResult
from gms_helpers.results import OperationResult


def _direct_return_false(_args):
    return False


def _direct_return_error(_args):
    return {"error": "bad input", "items": []}


def _direct_isolation_probe(args):
    Path(args.entered_path).write_text(str(Path.cwd()), encoding="utf-8")
    print(args.label)
    if args.release_path:
        deadline = time.monotonic() + 5
        while not Path(args.release_path).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not Path(args.release_path).exists():
            raise TimeoutError("isolation probe was not released")
    return True


def handle_runner_run(_args):
    return True


def _direct_sleep_until_killed(args):
    Path(args.entered_path).write_text("started", encoding="utf-8")
    time.sleep(60)
    return True


class TestCaptureOutputSystemExit(unittest.TestCase):
    def test_system_exit_nonzero_captured(self):
        def _fn():
            print("hello")
            print("oops", file=sys.stderr)
            raise SystemExit(2)

        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        self.assertFalse(ok)
        self.assertIn("hello", out)
        self.assertIn("oops", err)
        self.assertIsNone(result)
        self.assertIsNotNone(error_text)
        assert error_text is not None
        self.assertIn("SystemExit: 2", error_text)
        self.assertEqual(exit_code, 2)
        self.assertIn("stdout:", error_text)
        self.assertIn("stderr:", error_text)
        self.assertIn("hello", error_text)
        self.assertIn("oops", error_text)

    def test_system_exit_zero_ok(self):
        def _fn():
            print("done")
            raise SystemExit(0)

        ok, out, err, result, error_text, exit_code = _capture_output(_fn)
        self.assertTrue(ok)
        self.assertIn("done", out)
        self.assertEqual(err, "")
        self.assertIsNone(error_text)
        self.assertEqual(exit_code, 0)

    def test_direct_output_capture_is_bounded(self):
        def _fn():
            print("x" * 64, end="")
            sys.stderr.buffer.write(b"y" * 64)
            return True

        with patch("gms_mcp.server.direct_worker.DIRECT_CAPTURE_MAX_BYTES", 32):
            ok, out, err, _result, error_text, _exit_code = _capture_output(_fn)

        self.assertTrue(ok)
        self.assertEqual(out.split("\n[output", 1)[0], "x" * 32)
        self.assertEqual(err.split("\n[output", 1)[0], "y" * 32)
        self.assertIn("32 bytes omitted", out)
        self.assertIn("32 bytes omitted", err)
        self.assertIsNone(error_text)

    def test_cancelled_direct_thread_finishes_before_cancellation_propagates(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_worker():
            started.set()
            release.wait(timeout=5)
            finished.set()

        async def exercise():
            task = asyncio.create_task(_run_direct_thread_shielded(blocking_worker))
            while not started.is_set():
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(finished.is_set())

        asyncio.run(exercise())

    def test_cancellation_terminates_a_long_running_direct_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Probe.yyp").write_text("{}", encoding="utf-8")
            entered = root / "entered.txt"
            args = argparse.Namespace(entered_path=str(entered))

            async def exercise():
                task = asyncio.create_task(
                    _run_direct_thread_shielded(_run_direct, _direct_sleep_until_killed, args, str(root), 120)
                )
                deadline = time.monotonic() + 20
                while not entered.exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
                self.assertTrue(entered.exists())
                started = time.monotonic()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                return time.monotonic() - started

            self.assertLess(asyncio.run(exercise()), 10)


class TestDirectResultNormalization(unittest.TestCase):
    def _project_root(self):
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name)
        (root / "TestGame.yyp").write_text("{}", encoding="utf-8")
        self.addCleanup(temp_dir.cleanup)
        return root

    def test_run_direct_normalizes_legacy_bool_failure(self):
        result = _run_direct(_direct_return_false, argparse.Namespace(), str(self._project_root())).as_dict()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "_direct_return_false failed.")
        self.assertFalse(result["result"]["ok"])
        self.assertEqual(result["result"]["error"]["type"], "legacy_boolean_result")

    def test_handler_reference_recovers_module_when_test_file_runs_as_main(self):
        with patch.object(_direct_return_false, "__module__", "__main__"):
            module_name, qualname, module_root = _handler_reference(_direct_return_false)

        self.assertEqual(module_name, "test_mcp_direct")
        self.assertEqual(qualname, "_direct_return_false")
        self.assertEqual(module_root, Path(__file__).resolve().parent)

    def test_run_direct_normalizes_legacy_error_dict(self):
        result = _run_direct(_direct_return_error, argparse.Namespace(), str(self._project_root())).as_dict()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "bad input")
        self.assertFalse(result["result"]["ok"])
        self.assertEqual(result["result"]["error"]["code"], "legacy_dict_error")

    def test_timed_out_macos_runner_invokes_parent_owned_cleanup(self):
        project_root = self._project_root()
        process = MagicMock(pid=77, returncode=-15)
        process.communicate.side_effect = subprocess.TimeoutExpired(["worker"], 1)
        with (
            patch("gms_mcp.server.direct.subprocess.Popen", return_value=process),
            patch("gms_mcp.server.subprocess_runner._terminate_process_tree", return_value=True),
            patch("gms_mcp.server.macos_runner_timeout.cleanup_macos_ownership_manifest") as cleanup,
        ):
            result = _run_direct(
                handle_runner_run,
                argparse.Namespace(platform="macOS"),
                str(project_root),
                timeout_seconds=1,
            )

        self.assertTrue(result.timed_out)
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual(cleanup.call_args.args[0].name, "macos-runner-ownership.json")

    def test_concurrent_projects_cannot_cross_cwd_or_captured_output(self):
        original_cwd = Path.cwd()
        first_root = self._project_root()
        second_root = self._project_root()
        marker_temp = tempfile.TemporaryDirectory()
        self.addCleanup(marker_temp.cleanup)
        marker_root = Path(marker_temp.name)
        first_entered = marker_root / "first-entered"
        second_entered = marker_root / "second-entered"
        release_first = marker_root / "release-first"
        results = {}

        def run_first():
            results["first"] = _run_direct(
                _direct_isolation_probe,
                argparse.Namespace(
                    entered_path=str(first_entered),
                    release_path=str(release_first),
                    label="first-only",
                ),
                str(first_root),
            )

        def run_second():
            results["second"] = _run_direct(
                _direct_isolation_probe,
                argparse.Namespace(
                    entered_path=str(second_entered),
                    release_path="",
                    label="second-only",
                ),
                str(second_root),
            )

        first_thread = threading.Thread(target=run_first)
        second_thread = threading.Thread(target=run_second)
        first_thread.start()
        deadline = time.monotonic() + 5
        while not first_entered.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(first_entered.exists())
        second_thread.start()
        try:
            deadline = time.monotonic() + 5
            while not second_entered.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(second_entered.exists(), "isolated second call did not run concurrently")
        finally:
            release_first.write_text("release", encoding="utf-8")
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(Path(first_entered.read_text(encoding="utf-8")), first_root.resolve())
        self.assertEqual(Path(second_entered.read_text(encoding="utf-8")), second_root.resolve())
        self.assertEqual(Path.cwd(), original_cwd)
        self.assertIn("first-only", results["first"].stdout)
        self.assertNotIn("second-only", results["first"].stdout)
        self.assertIn("second-only", results["second"].stdout)
        self.assertNotIn("first-only", results["second"].stdout)

    def test_relative_sibling_project_is_anchored_before_direct_cwd_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            first_root = base / "one"
            second_root = base / "two"
            first_root.mkdir()
            second_root.mkdir()
            (first_root / "One.yyp").write_text("{}", encoding="utf-8")
            (second_root / "Two.yyp").write_text("{}", encoding="utf-8")
            first_entered = base / "first-entered"
            second_entered = base / "second-entered"
            release_first = base / "release-first"
            results = {}

            def run_second():
                results["second"] = _run_direct(
                    _direct_isolation_probe,
                    argparse.Namespace(entered_path=str(second_entered), release_path="", label="second"),
                    "two",
                )

            with patch.object(server_project, "_SERVER_START_DIRECTORY", base):
                first_thread = threading.Thread(
                    target=_run_direct,
                    args=(
                        _direct_isolation_probe,
                        argparse.Namespace(
                            entered_path=str(first_entered),
                            release_path=str(release_first),
                            label="first",
                        ),
                        "one",
                    ),
                )
                first_thread.start()
                deadline = time.monotonic() + 5
                while not first_entered.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(first_entered.exists())
                second_thread = threading.Thread(target=run_second)
                second_thread.start()
                try:
                    deadline = time.monotonic() + 5
                    while not second_entered.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(second_entered.exists())
                finally:
                    release_first.write_text("release", encoding="utf-8")
                first_thread.join(timeout=5)
                second_thread.join(timeout=5)

            self.assertTrue(results["second"].ok)
            self.assertEqual(Path(first_entered.read_text(encoding="utf-8")), first_root.resolve())
            self.assertEqual(Path(second_entered.read_text(encoding="utf-8")), second_root.resolve())


class TestRunWithFallbackDefaults(unittest.TestCase):
    def test_direct_result_preserves_structured_return_value(self):
        result = ToolRunResult(
            ok=True,
            stdout="",
            stderr="",
            direct_used=True,
            result=OperationResult(success=True, message="done", warnings=["note"]),
        ).as_dict()

        self.assertEqual(result["result"]["message"], "done")
        self.assertEqual(result["result"]["warnings"], ["note"])

    def test_default_uses_cli_when_direct_disabled(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {}, clear=True):
            with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                    result = asyncio.run(
                        server._run_with_fallback(
                            direct_handler=lambda _args: True,
                            direct_args=argparse.Namespace(),
                            cli_args=["event", "list", "o_player"],
                            project_root=".",
                            prefer_cli=False,
                            output_mode="full",
                            quiet=True,
                        )
                    )

        self.assertFalse(result["direct_used"])
        self.assertTrue(mock_cli.called)
        self.assertFalse(mock_direct.called)

    def test_opt_in_direct_via_env(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "1"}, clear=True):
            # Re-initialize policy manager to pick up env var
            from gms_mcp.execution_policy import PolicyManager

            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                        result = asyncio.run(
                            server._run_with_fallback(
                                direct_handler=lambda _args: True,
                                direct_args=argparse.Namespace(),
                                cli_args=["event", "list", "o_player"],
                                project_root=".",
                                prefer_cli=False,
                                output_mode="full",
                                quiet=True,
                            )
                        )

        self.assertTrue(result["direct_used"])
        self.assertTrue(mock_direct.called)
        self.assertFalse(mock_cli.called)

    def test_direct_domain_failure_does_not_fallback_to_cli(self):
        direct_result = ToolRunResult(
            ok=False,
            stdout="",
            stderr="",
            direct_used=True,
            exit_code=9,
            error="ValidationError: invalid asset name",
        )
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "1"}, clear=True):
            from gms_mcp.execution_policy import PolicyManager

            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                        result = asyncio.run(
                            server._run_with_fallback(
                                direct_handler=lambda _args: True,
                                direct_args=argparse.Namespace(),
                                cli_args=["asset", "create", "object", "player"],
                                project_root=".",
                                prefer_cli=False,
                                output_mode="full",
                                quiet=True,
                            )
                        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["direct_used"])
        self.assertTrue(result["fallback_skipped"])
        self.assertEqual(result["fallback_skipped_reason"], "direct_domain_failure")
        self.assertTrue(mock_direct.called)
        self.assertFalse(mock_cli.called)

    def _run_direct_failure(self, direct_result, cli_args, direct_args=None):
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "1"}, clear=True):
            from gms_mcp.execution_policy import PolicyManager

            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                        result = asyncio.run(
                            server._run_with_fallback(
                                direct_handler=lambda _args: True,
                                direct_args=direct_args or argparse.Namespace(),
                                cli_args=cli_args,
                                project_root=".",
                                prefer_cli=False,
                                output_mode="full",
                                quiet=True,
                            )
                        )
        self.assertTrue(mock_direct.called)
        return result, mock_cli

    def test_direct_infrastructure_failure_of_a_reader_still_falls_back_to_cli(self):
        direct_result = ToolRunResult(
            ok=False,
            stdout="",
            stderr="",
            direct_used=True,
            error="Traceback (most recent call last):\nImportError: helper unavailable",
        )
        result, mock_cli = self._run_direct_failure(direct_result, ["event", "list", "--", "o_player"])

        self.assertTrue(result["ok"])
        self.assertFalse(result["direct_used"])
        self.assertEqual(result["direct_error"], direct_result.error)
        self.assertTrue(mock_cli.called)

    def test_direct_infrastructure_failure_of_a_writer_never_reruns_through_cli(self):
        direct_result = ToolRunResult(
            ok=False,
            stdout="",
            stderr="",
            direct_used=True,
            error="Traceback (most recent call last):\nImportError: helper unavailable",
        )
        result, mock_cli = self._run_direct_failure(
            direct_result, ["asset", "create", "object", "--parent-path", "folders/Objects.yy", "--", "o_player"]
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["fallback_skipped_reason"], "project_mutation")
        self.assertFalse(mock_cli.called)

    def test_direct_timeout_never_reruns_through_cli(self):
        direct_result = ToolRunResult(
            ok=False, stdout="", stderr="", direct_used=True, error="Direct worker timed out", timed_out=True
        )
        result, mock_cli = self._run_direct_failure(direct_result, ["event", "list", "--", "o_player"])

        self.assertFalse(result["ok"])
        self.assertEqual(result["fallback_skipped_reason"], "direct_timeout")
        self.assertFalse(mock_cli.called)

    def test_dash_leading_values_are_data_and_parser_exits_never_escape(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "1"}, clear=True):
            from gms_mcp.execution_policy import PolicyManager

            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    as_data = asyncio.run(
                        server._run_with_fallback(
                            direct_handler=lambda _args: True,
                            direct_args=argparse.Namespace(),
                            cli_args=["room", "layer", "remove", "--", "r_main", "-h"],
                            project_root=".",
                            prefer_cli=False,
                            quiet=True,
                        )
                    )
                    unparseable = asyncio.run(
                        server._run_with_fallback(
                            direct_handler=lambda _args: True,
                            direct_args=argparse.Namespace(),
                            cli_args=["room", "layer", "remove", "r_main", "-h"],
                            project_root=".",
                            prefer_cli=False,
                            quiet=True,
                        )
                    )

        self.assertTrue(as_data["ok"])
        self.assertEqual(mock_direct.call_count, 1)
        self.assertFalse(unparseable["ok"])
        self.assertIn("could not be parsed", unparseable["error"])

    def test_every_operation_policy_writer_is_blocked_from_cli(self):
        from gms_mcp.server.destructive_policy import is_real_destructive_cli_workflow

        for name in (
            "event-add",
            "event-duplicate",
            "sprite-frames-add",
            "sprite-frames-duplicate",
            "room-layer-add",
            "room-instance-add",
        ):
            self.assertTrue(is_real_destructive_cli_workflow(name, argparse.Namespace()), name)
        self.assertFalse(is_real_destructive_cli_workflow("room-ops-delete", argparse.Namespace(dry_run=True)))

    def test_real_destructive_default_uses_direct_not_cli(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {}, clear=True):
            from gms_mcp.execution_policy import PolicyManager

            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                        result = asyncio.run(
                            server._run_with_fallback(
                                direct_handler=lambda _args: True,
                                direct_args=argparse.Namespace(dry_run=False),
                                cli_args=["workflow", "rename", "scripts/scr_old/scr_old.yy", "scr_new"],
                                project_root=".",
                                prefer_cli=False,
                                output_mode="full",
                                quiet=True,
                            )
                        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["direct_used"])
        self.assertTrue(mock_direct.called)
        self.assertFalse(mock_cli.called)

    def test_prefer_cli_blocked_for_real_destructive_workflow(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
            with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                result = asyncio.run(
                    server._run_with_fallback(
                        direct_handler=lambda _args: True,
                        direct_args=argparse.Namespace(dry_run=False),
                        cli_args=["workflow", "rename", "scripts/scr_old/scr_old.yy", "scr_new"],
                        project_root=".",
                        prefer_cli=True,
                        output_mode="full",
                        quiet=True,
                    )
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["policy"], "destructive_cli_disabled")
        self.assertTrue(result["fallback_skipped"])
        self.assertEqual(result["fallback_skipped_reason"], "destructive_cli_disabled")
        self.assertFalse(mock_direct.called)
        self.assertFalse(mock_cli.called)

    def test_real_destructive_infrastructure_failure_does_not_fallback_to_cli(self):
        direct_result = ToolRunResult(
            ok=False,
            stdout="",
            stderr="",
            direct_used=True,
            error="Traceback (most recent call last):\nImportError: helper unavailable",
        )
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {"GMS_MCP_ENABLE_DIRECT": "1"}, clear=True):
            from gms_mcp.execution_policy import PolicyManager

            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                        result = asyncio.run(
                            server._run_with_fallback(
                                direct_handler=lambda _args: True,
                                direct_args=argparse.Namespace(dry_run=False),
                                cli_args=["workflow", "rename", "scripts/scr_old/scr_old.yy", "scr_new"],
                                project_root=".",
                                prefer_cli=False,
                                output_mode="full",
                                quiet=True,
                            )
                        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["direct_used"])
        self.assertTrue(result["fallback_skipped"])
        self.assertEqual(result["fallback_skipped_reason"], "destructive_cli_disabled")
        self.assertTrue(result["fallback_blocked_by_policy"])
        self.assertTrue(mock_direct.called)
        self.assertFalse(mock_cli.called)

    def test_destructive_dry_run_can_use_cli_default(self):
        direct_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=True)
        cli_result = ToolRunResult(ok=True, stdout="", stderr="", direct_used=False)

        async def _fake_cli(*_args, **_kwargs):
            return cli_result

        with patch.dict(os.environ, {}, clear=True):
            from gms_mcp.execution_policy import PolicyManager

            with patch("gms_mcp.server.dispatch.policy_manager", PolicyManager()):
                with patch("gms_mcp.server.dispatch._run_direct", return_value=direct_result) as mock_direct:
                    with patch("gms_mcp.server.dispatch._run_cli_async", side_effect=_fake_cli) as mock_cli:
                        result = asyncio.run(
                            server._run_with_fallback(
                                direct_handler=lambda _args: True,
                                direct_args=argparse.Namespace(dry_run=True),
                                cli_args=["room", "ops", "delete", "r_old", "--dry-run"],
                                project_root=".",
                                prefer_cli=False,
                                output_mode="full",
                                quiet=True,
                            )
                        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["direct_used"])
        self.assertFalse(mock_direct.called)
        self.assertTrue(mock_cli.called)


class TestDryRunPolicyAllowlist(unittest.TestCase):
    def test_require_dry_run_enforced_without_allowlist(self):
        with patch.dict(os.environ, {"GMS_MCP_REQUIRE_DRY_RUN": "1"}, clear=True):
            self.assertTrue(_requires_dry_run_for_tool("gm_safe_delete"))

    def test_require_dry_run_allowlist_bypasses_named_tool(self):
        with patch.dict(
            os.environ,
            {
                "GMS_MCP_REQUIRE_DRY_RUN": "1",
                "GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST": "gm_safe_delete",
            },
            clear=True,
        ):
            self.assertFalse(_requires_dry_run_for_tool("gm_safe_delete"))
            self.assertTrue(_requires_dry_run_for_tool("gm_room_ops_delete"))

    def test_require_dry_run_allowlist_semicolon_and_case_insensitive(self):
        with patch.dict(
            os.environ,
            {
                "GMS_MCP_REQUIRE_DRY_RUN": "1",
                "GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST": "GM_SAFE_DELETE",
            },
            clear=True,
        ):
            self.assertFalse(_requires_dry_run_for_tool("gm_safe_delete"))


if __name__ == "__main__":
    unittest.main()
