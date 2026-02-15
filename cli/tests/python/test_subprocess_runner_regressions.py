#!/usr/bin/env python3
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


class TestSubprocessRunnerRegressions(unittest.TestCase):
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
            result = asyncio.run(
                _run_subprocess_async(
                    cmd,
                    cwd=cwd,
                    timeout_seconds=1,
                    heartbeat_seconds=0.1,
                    tool_name="pytest-timeout",
                    execution_mode="test",
                )
            )

            self.assertFalse(result.ok)
            self.assertTrue(result.timed_out)
            self.assertIsNotNone(result.log_file)
            log_path = Path(result.log_file)
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            self.assertIn("TIMEOUT", log_text)

    def test_cancellation_terminates_process_and_does_not_hang(self):
        from gms_mcp.server.subprocess_runner import _run_subprocess_async

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
            cwd = Path(td)
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(_cancel_flow(cwd))

            log_dir = cwd / ".gms_mcp" / "logs"
            self.assertTrue(log_dir.exists())
            log_files = sorted(log_dir.glob("pytest-cancel-*.log"), key=lambda p: p.stat().st_mtime)
            self.assertTrue(log_files, msg=f"No log files found in {log_dir}")
            log_text = log_files[-1].read_text(encoding="utf-8", errors="replace")
            self.assertIn("CANCELLED", log_text)


if __name__ == "__main__":
    unittest.main()

