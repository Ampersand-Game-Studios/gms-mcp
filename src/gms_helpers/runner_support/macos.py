from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional


class RunnerMacOSMixin:
    def _macos_debug_log_path(self) -> Path:
        """Return the debug log path written by local macOS Run builds."""
        project_name = self.find_project_file().stem
        return self.project_root / "output" / project_name / "debug.log"

    def _wait_for_macos_main_loop(
        self,
        process: subprocess.Popen,
        log_path: Path,
        start_offset: int,
        timeout_seconds: float = 90.0,
    ) -> bool:
        """Wait for the local macOS runner to report that it reached the main loop."""
        deadline = time.monotonic() + timeout_seconds

        def _log_contains_main_loop() -> bool:
            if not log_path.exists():
                return False

            try:
                current_size = log_path.stat().st_size
                offset = start_offset if current_size >= start_offset else 0
                with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    handle.seek(offset)
                    return "Entering main loop." in handle.read()
            except OSError:
                return False

        while time.monotonic() < deadline:
            if _log_contains_main_loop():
                return True
            if process.poll() is not None:
                break
            time.sleep(0.5)

        return _log_contains_main_loop()

    def _wait_for_macos_runner_start(
        self,
        process: subprocess.Popen,
        game_path: Path,
        debug_log_path: Path,
        baseline_runner_pids: set[int],
        baseline_tail_pids: set[int],
        timeout_seconds: float = 120.0,
    ) -> tuple[Optional[int], set[int], set[int]]:
        """Wait for a new macOS local run helper process to appear for this project."""
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            runner_pids, tail_pids = self._find_macos_validation_helper_pids(game_path, debug_log_path)
            new_runner_pids = runner_pids - baseline_runner_pids
            new_tail_pids = tail_pids - baseline_tail_pids
            if new_runner_pids:
                return max(new_runner_pids), new_runner_pids, new_tail_pids
            if process.poll() is not None:
                return None, new_runner_pids, new_tail_pids
            time.sleep(0.5)

        runner_pids, tail_pids = self._find_macos_validation_helper_pids(game_path, debug_log_path)
        new_runner_pids = runner_pids - baseline_runner_pids
        new_tail_pids = tail_pids - baseline_tail_pids
        runner_pid = max(new_runner_pids) if new_runner_pids else None
        return runner_pid, new_runner_pids, new_tail_pids

    def _stop_platform_process(self, platform_target: str, runtime_type: str = "VM") -> bool:
        """Ask Igor to stop the currently running local target process."""
        cmd = self._build_platform_action_command("Stop", platform_target, runtime_type)
        print(f"[CMD] Stop command: {' '.join(cmd)}")

        process_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
            "universal_newlines": True,
        }
        process_kwargs.update(self._normalize_path_for_popen())
        completed = subprocess.run(cmd, check=False, **process_kwargs)

        if completed.stdout:
            for line in completed.stdout.splitlines():
                line = line.strip()
                if line:
                    print(f"   {line}")

        return completed.returncode == 0

    def _find_macos_validation_helper_pids(self, game_path: Path, debug_log_path: Path) -> tuple[set[int], set[int]]:
        """Return macOS runner/tail helper PIDs associated with a specific local run."""
        completed = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        runner_pids: set[int] = set()
        tail_pids: set[int] = set()
        game_token = str(game_path)
        debug_token = str(debug_log_path)

        for raw_line in completed.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue

            command = parts[1]
            if "Mac_Runner" in command and game_token in command:
                runner_pids.add(pid)
            elif "tail -F" in command and debug_token in command:
                tail_pids.add(pid)

        return runner_pids, tail_pids

    def _terminate_pid(self, pid: int, label: str) -> None:
        """Terminate a helper process, escalating to SIGKILL if needed."""
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as exc:
            print(f"[WARN] Failed to terminate {label} process {pid}: {exc}")
            return

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.2)

        force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)

        try:
            os.kill(pid, force_signal)
        except ProcessLookupError:
            return
        except Exception as exc:
            print(f"[WARN] Failed to force-kill {label} process {pid}: {exc}")

    def _cleanup_macos_validation_helpers(
        self,
        game_path: Path,
        debug_log_path: Path,
        baseline_runner_pids: set[int],
        baseline_tail_pids: set[int],
    ) -> None:
        """Remove helper processes spawned by a compile-time local run validation."""
        runner_pids, tail_pids = self._find_macos_validation_helper_pids(game_path, debug_log_path)
        new_runner_pids = sorted(runner_pids - baseline_runner_pids)
        new_tail_pids = sorted(tail_pids - baseline_tail_pids)

        for pid in new_runner_pids:
            print(f"[BUILD] Terminating validation runner PID {pid}...")
            self._terminate_pid(pid, "runner")

        for pid in new_tail_pids:
            print(f"[BUILD] Terminating validation log tail PID {pid}...")
            self._terminate_pid(pid, "tail")

    def _stop_macos_run_session(self, session) -> Dict[str, Any]:
        """Stop a macOS local run session tracked by the actual runner PID."""
        game_path = Path(session.exe_path)
        debug_log_path = Path(session.log_file) if session.log_file else self._macos_debug_log_path()
        runner_pids, tail_pids = self._find_macos_validation_helper_pids(game_path, debug_log_path)
        tracked_runner_pids = set(runner_pids)
        tracked_tail_pids = set(tail_pids)
        if session.pid > 0:
            tracked_runner_pids.add(session.pid)

        print(f"[STOP] Stopping macOS local run (Runner PID: {session.pid})...")
        stop_ok = self._stop_platform_process("macOS", session.runtime_type)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            live_runner_pids = {pid for pid in tracked_runner_pids if self._session_manager.is_process_alive(pid)}
            live_tail_pids = {pid for pid in tracked_tail_pids if self._session_manager.is_process_alive(pid)}
            if not live_runner_pids and not live_tail_pids:
                self._session_manager.clear_session()
                message = (
                    f"macOS local run (PID: {session.pid}) stopped successfully."
                    if stop_ok
                    else f"macOS local run (PID: {session.pid}) stopped after helper cleanup."
                )
                return {"ok": True, "message": message}
            time.sleep(0.2)

        live_runner_pids = {pid for pid in tracked_runner_pids if self._session_manager.is_process_alive(pid)}
        live_tail_pids = {pid for pid in tracked_tail_pids if self._session_manager.is_process_alive(pid)}

        for pid in sorted(live_runner_pids):
            print(f"[STOP] Terminating lingering macOS runner PID {pid}...")
            self._terminate_pid(pid, "runner")

        for pid in sorted(live_tail_pids):
            print(f"[STOP] Terminating lingering macOS log tail PID {pid}...")
            self._terminate_pid(pid, "tail")

        remaining_runner_pids = {pid for pid in tracked_runner_pids if self._session_manager.is_process_alive(pid)}
        remaining_tail_pids = {pid for pid in tracked_tail_pids if self._session_manager.is_process_alive(pid)}
        self._session_manager.clear_session()

        if remaining_runner_pids or remaining_tail_pids:
            return {
                "ok": False,
                "message": (
                    "Failed to stop macOS local run completely. "
                    f"Runner PIDs still alive: {sorted(remaining_runner_pids)}; "
                    f"log tail PIDs still alive: {sorted(remaining_tail_pids)}"
                ),
            }

        message = (
            f"macOS local run (PID: {session.pid}) stopped successfully."
            if stop_ok
            else f"macOS local run (PID: {session.pid}) stopped after manual cleanup."
        )
        return {"ok": True, "message": message}
