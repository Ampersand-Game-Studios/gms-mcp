#!/usr/bin/env python3
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class TestSubprocessRunnerRegressions(unittest.TestCase):
    def test_command_logging_redacts_secret_flags(self):
        from gms_mcp.server import subprocess_runner

        command = [
            "igor",
            "runtime",
            "FetchLicense",
            "-ak=private-access-key",
            "--token",
            "private-token",
            "--project",
            "game.yyp",
        ]

        redacted = subprocess_runner._redact_command(command)

        self.assertNotIn("private-access-key", " ".join(redacted))
        self.assertNotIn("private-token", " ".join(redacted))
        self.assertIn("-ak=[REDACTED]", redacted)
        self.assertEqual(redacted[-2:], ["--project", "game.yyp"])

    def _assert_process_exited(self, pid: int) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail(f"descendant process {pid} was still alive after tree termination")

    def test_subprocess_is_created_in_an_isolated_process_group(self):
        from gms_mcp.server import subprocess_runner

        kwargs = subprocess_runner._spawn_kwargs()
        if os.name == "nt":
            self.assertTrue(kwargs["creationflags"])
        else:
            self.assertEqual(kwargs, {"start_new_session": True})
        with patch.object(subprocess_runner.os, "name", "nt"):
            self.assertEqual(subprocess_runner._spawn_kwargs(), {"creationflags": 0x00000200})

    def test_windows_tree_termination_uses_taskkill_and_verifies_parent_exit(self):
        from gms_mcp.server import subprocess_runner

        process = Mock(pid=321)
        process.poll.return_value = 0
        completed = Mock(returncode=0)
        with (
            patch.object(subprocess_runner.os, "name", "nt"),
            patch.object(subprocess_runner.subprocess, "run", return_value=completed) as taskkill,
        ):
            self.assertTrue(subprocess_runner._terminate_process_tree(process))

        taskkill.assert_called_once_with(
            ["taskkill", "/PID", "321", "/T", "/F"],
            capture_output=True,
            text=True,
        )
        process.wait.assert_called_once()

    def test_timeout_terminates_process_and_returns_timed_out(self):
        from gms_mcp.server.subprocess_runner import _run_subprocess_async

        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            cmd = [
                sys.executable,
                "-u",
                "-c",
                "import time; print('start', flush=True); time.sleep(60)",
            ]
            ownership_manifest = cwd / "ownership.json"
            with patch("gms_mcp.server.macos_runner_timeout.cleanup_macos_ownership_manifest") as cleanup:
                result = asyncio.run(
                    _run_subprocess_async(
                        cmd,
                        cwd=cwd,
                        timeout_seconds=1,
                        heartbeat_seconds=0.1,
                        tool_name="pytest-timeout",
                        execution_mode="test",
                        ownership_manifest_path=ownership_manifest,
                    )
                )
            self.assertGreaterEqual(cleanup.call_count, 1)
            cleanup.assert_called_with(ownership_manifest)

            self.assertFalse(result.ok)
            self.assertTrue(result.timed_out)
            self.assertIsNotNone(result.log_file)
            log_path = Path(result.log_file)
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            self.assertIn("TIMEOUT", log_text)

    def test_natural_nonzero_exit_invokes_parent_owned_cleanup(self):
        from gms_mcp.server.subprocess_runner import _run_subprocess_async

        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            ownership_manifest = cwd / "ownership.json"
            with patch("gms_mcp.server.macos_runner_timeout.cleanup_macos_ownership_manifest") as cleanup:
                result = asyncio.run(
                    _run_subprocess_async(
                        [sys.executable, "-c", "raise SystemExit(3)"],
                        cwd=cwd,
                        timeout_seconds=5,
                        tool_name="pytest-natural-failure",
                        ownership_manifest_path=ownership_manifest,
                    )
                )
        self.assertFalse(result.ok)
        cleanup.assert_called_once_with(ownership_manifest)

    @unittest.skipIf(os.name == "nt", "POSIX process-group regression")
    def test_timeout_terminates_spawned_descendants(self):
        from gms_mcp.server.subprocess_runner import _run_subprocess_async

        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            child_code = (
                "import subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "print(child.pid,flush=True); time.sleep(60)"
            )
            result = asyncio.run(
                _run_subprocess_async(
                    [sys.executable, "-u", "-c", child_code],
                    cwd=cwd,
                    timeout_seconds=1,
                    heartbeat_seconds=0.1,
                    tool_name="pytest-descendant-timeout",
                    execution_mode="test",
                )
            )

            self.assertTrue(result.timed_out)
            descendant_pid = int(result.stdout.splitlines()[0])
            self._assert_process_exited(descendant_pid)

    def test_cancellation_terminates_process_and_does_not_hang(self):
        from gms_mcp.server.subprocess_runner import _ensure_log_dir, _run_subprocess_async

        async def _cancel_flow(tmp: Path) -> None:
            cmd = [
                sys.executable,
                "-u",
                "-c",
                "import time; print('start', flush=True); time.sleep(60)",
            ]
            tool_name = "pytest-cancel"
            task = asyncio.create_task(
                _run_subprocess_async(
                    cmd,
                    cwd=tmp,
                    timeout_seconds=None,
                    heartbeat_seconds=0.1,
                    tool_name=tool_name,
                    execution_mode="test",
                )
            )
            await asyncio.sleep(0.5)
            task.cancel()
            # Ensure cancellation propagates quickly (i.e., we actually terminate).
            await asyncio.wait_for(task, timeout=8)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cwd = root / "project"
            home = root / "home"
            cwd.mkdir()
            home.mkdir()
            with patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(_cancel_flow(cwd))

                log_dir = _ensure_log_dir(cwd)
                self.assertTrue(log_dir.exists())
                log_files = sorted(log_dir.glob("pytest-cancel-*.log"), key=lambda p: p.stat().st_mtime)
                self.assertTrue(log_files, msg=f"No log files found in {log_dir}")
                log_text = log_files[-1].read_text(encoding="utf-8", errors="replace")
                self.assertIn("CANCELLED", log_text)
                self.assertFalse((cwd / ".gms_mcp").exists())

    @unittest.skipIf(os.name == "nt", "POSIX process-group regression")
    def test_cancellation_terminates_spawned_descendants(self):
        from gms_mcp.server.subprocess_runner import _ensure_log_dir, _run_subprocess_async

        async def _cancel_flow(tmp: Path) -> int:
            child_code = (
                "import subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "print(child.pid,flush=True); time.sleep(60)"
            )
            tool_name = "pytest-descendant-cancel"
            task = asyncio.create_task(
                _run_subprocess_async(
                    [sys.executable, "-u", "-c", child_code],
                    cwd=tmp,
                    timeout_seconds=None,
                    heartbeat_seconds=0.1,
                    tool_name=tool_name,
                    execution_mode="test",
                )
            )
            log_dir = _ensure_log_dir(tmp)
            descendant_pid = None
            deadline = time.monotonic() + 5
            while descendant_pid is None and time.monotonic() < deadline:
                for log_path in log_dir.glob(f"{tool_name}-*.log"):
                    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.startswith("[stdout] "):
                            descendant_pid = int(line.removeprefix("[stdout] "))
                            break
                await asyncio.sleep(0.05)
            self.assertIsNotNone(descendant_pid)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=8)
            return int(descendant_pid)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            home.mkdir()
            with patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                descendant_pid = asyncio.run(_cancel_flow(project))
                self._assert_process_exited(descendant_pid)

    def test_log_filename_is_sanitized_and_unique(self):
        from gms_mcp.server.subprocess_runner import _ensure_log_dir, _new_log_path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cwd = root / "project"
            other_project = root / "other-project"
            home = root / "home"
            cwd.mkdir()
            other_project.mkdir()
            home.mkdir()
            with patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                first = _new_log_path(cwd, "../../unsafe tool 🔥")
                second = _new_log_path(cwd, "../../unsafe tool 🔥")
                other = _new_log_path(other_project, "other")
                self.assertEqual(first.parent, _ensure_log_dir(cwd))

            self.assertTrue(first.parent.is_relative_to(home / ".gms-mcp" / "logs"))
            self.assertNotEqual(first.parent, other.parent)
            self.assertEqual(len(first.parent.name), 16)
            self.assertFalse((cwd / ".gms_mcp").exists())
            self.assertNotIn("..", first.name)
            self.assertNotIn("/", first.name)
            self.assertNotEqual(first, second)

    def test_subprocess_capture_and_active_log_are_bounded_while_draining(self):
        from gms_mcp.server import subprocess_runner

        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            child_code = "import os; os.write(1, b'x' * 4096); os.write(2, b'y' * 4096)"
            with (
                patch.object(subprocess_runner, "SUBPROCESS_CAPTURE_MAX_BYTES", 256),
                patch.object(subprocess_runner, "LOG_MAX_ACTIVE_BYTES", 512),
            ):
                result = asyncio.run(
                    subprocess_runner._run_subprocess_async(
                        [sys.executable, "-u", "-c", child_code],
                        cwd=cwd,
                        timeout_seconds=5,
                        tool_name="bounded-output",
                        execution_mode="test",
                    )
                )

            self.assertTrue(result.ok)
            self.assertIn("3840 bytes omitted", result.stdout)
            self.assertIn("3840 bytes omitted", result.stderr)
            self.assertTrue(result.stdout.endswith("x" * 256))
            self.assertTrue(result.stderr.endswith("y" * 256))
            log_path = Path(result.log_file)
            self.assertLessEqual(log_path.stat().st_size, 512)
            self.assertIn("LOG TRUNCATED", log_path.read_text(encoding="utf-8", errors="replace"))

    def test_log_pruning_keeps_active_and_latest_complete_logs(self):
        from gms_mcp.server import subprocess_runner

        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td)
            active = log_dir / "active.log"
            old = log_dir / "old.log"
            newer = log_dir / "newer.log"
            latest = log_dir / "latest.log"
            for index, path in enumerate((active, old, newer, latest), start=1):
                path.write_text("x" * 10, encoding="utf-8")
                os.utime(path, (index, index))
            subprocess_runner._active_marker_path(active).write_text("active", encoding="utf-8")

            with (
                patch.object(subprocess_runner, "LOG_MAX_COMPLETED_FILES", 2),
                patch.object(subprocess_runner, "LOG_MAX_COMPLETED_BYTES", 15),
            ):
                subprocess_runner._prune_log_dir(log_dir, keep=latest)

            self.assertTrue(active.exists())
            self.assertTrue(latest.exists())
            self.assertFalse(old.exists())
            self.assertFalse(newer.exists())

    def test_latest_complete_invocation_log_survives_byte_and_file_caps(self):
        from gms_mcp.server import subprocess_runner

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cwd = root / "project"
            home = root / "home"
            cwd.mkdir()
            home.mkdir()
            with patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                log_dir = subprocess_runner._ensure_log_dir(cwd)
            old = log_dir / "old.log"
            old.write_text("old", encoding="utf-8")
            os.utime(old, (1, 1))

            with (
                patch.object(subprocess_runner, "LOG_MAX_COMPLETED_FILES", 1),
                patch.object(subprocess_runner, "LOG_MAX_COMPLETED_BYTES", 1),
            ):
                with patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                    result = asyncio.run(
                        subprocess_runner._run_subprocess_async(
                            [sys.executable, "-u", "-c", "print('complete-log')"],
                            cwd=cwd,
                            timeout_seconds=5,
                            tool_name="latest-log",
                            execution_mode="test",
                        )
                    )

            self.assertTrue(result.ok)
            latest = Path(result.log_file)
            self.assertTrue(latest.exists())
            self.assertIn("[stdout] complete-log", latest.read_text(encoding="utf-8"))
            self.assertFalse(old.exists())
            self.assertFalse(subprocess_runner._active_marker_path(latest).exists())


if __name__ == "__main__":
    unittest.main()
