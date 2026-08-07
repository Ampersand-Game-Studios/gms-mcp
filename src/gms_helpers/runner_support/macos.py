from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import json
import os
import platform
import secrets
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..exceptions import RuntimeNotFoundError
from ..runner_process import build_igor_environment


@dataclass(frozen=True)
class MacOSProcess:
    """Minimal process identity used for runner ownership decisions."""

    pid: int
    ppid: int
    command: str
    started: str = ""


class RunnerMacOSMixin:
    _MACOS_OWNERSHIP_MANIFEST_ENV = "GMS_MCP_MACOS_OWNERSHIP_MANIFEST"
    _MACOS_LAUNCH_TOKEN_ENV = "GMS_MCP_MACOS_LAUNCH_TOKEN"

    @staticmethod
    def _igor_idle_wait_seconds() -> float:
        raw = os.environ.get("GMS_MCP_IGOR_IDLE_WAIT_SECONDS", "30").strip()
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 30.0

    def _find_active_igor_processes(self) -> dict[int, MacOSProcess]:
        """Return live Igor processes, including IDE-originated builds."""
        if platform.system() != "Darwin":
            return {}
        completed = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,state=,comm="],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        active: dict[int, MacOSProcess] = {}
        for raw_line in completed.stdout.splitlines():
            parts = raw_line.strip().split(None, 3)
            if len(parts) != 4:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            try:
                ppid = int(parts[1])
            except ValueError:
                continue
            state, command = parts[2], parts[3]
            if state.startswith("Z"):
                continue
            if Path(command).name == "Igor":
                active[pid] = MacOSProcess(pid=pid, ppid=ppid, command=command)
        return active

    def _wait_for_igor_idle(self, timeout_seconds: Optional[float] = None) -> None:
        """Wait briefly for all Igor activity to end, then fail clearly."""
        if platform.system() != "Darwin":
            return
        timeout = self._igor_idle_wait_seconds() if timeout_seconds is None else max(0.0, timeout_seconds)
        deadline = time.monotonic() + timeout
        active = self._find_active_igor_processes()
        if active and timeout > 0:
            print(
                "[WAIT] Existing GameMaker/Igor build-run activity detected; "
                f"waiting up to {timeout:g} seconds for PID(s) {sorted(active)}."
            )
        while active and time.monotonic() < deadline:
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
            active = self._find_active_igor_processes()
        if active:
            raise RuntimeError(
                "GameMaker is already building or running through Igor "
                f"(PID(s): {sorted(active)}). Refusing to overlap another build-run after waiting "
                f"{timeout:g} seconds. Stop or finish the existing GameMaker run, then retry."
            )

    def _snapshot_macos_processes(self) -> dict[int, MacOSProcess]:
        """Snapshot process identity before an owned macOS runner launch."""
        if platform.system() != "Darwin":
            return {}
        completed = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,lstart=,command="],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        processes: dict[int, MacOSProcess] = {}
        for raw_line in completed.stdout.splitlines():
            parts = raw_line.strip().split(None, 7)
            if len(parts) < 3:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            try:
                ppid = int(parts[1])
            except ValueError:
                processes[pid] = MacOSProcess(pid=pid, ppid=0, command=" ".join(parts[1:]))
                continue
            if len(parts) == 8:
                started = " ".join(parts[2:7])
                command = parts[7]
            else:
                started = ""
                command = " ".join(parts[2:])
            processes[pid] = MacOSProcess(pid=pid, ppid=ppid, command=command, started=started)
        return processes

    @staticmethod
    def _macos_runner_pids(processes: dict[int, MacOSProcess]) -> set[int]:
        return {pid for pid, process in processes.items() if "/Mac_Runner" in process.command}

    @staticmethod
    def _macos_tail_pids(processes: dict[int, MacOSProcess]) -> set[int]:
        return {pid for pid, process in processes.items() if "tail -F" in process.command}

    @classmethod
    def _matches_macos_baseline(
        cls,
        pid: int,
        process: MacOSProcess,
        baseline: set[int] | dict[int, MacOSProcess],
    ) -> bool:
        """Exclude only the exact prelaunch identity, never a recycled PID."""
        if isinstance(baseline, dict):
            return cls._same_macos_process_identity(process, baseline.get(pid))
        return pid in baseline

    @staticmethod
    def _is_descendant_of(pid: int, ancestor_pid: int, processes: dict[int, MacOSProcess]) -> bool:
        visited: set[int] = set()
        current = processes.get(pid)
        while current and current.ppid > 0 and current.ppid not in visited:
            if current.ppid == ancestor_pid:
                return True
            visited.add(current.ppid)
            current = processes.get(current.ppid)
        return False

    @staticmethod
    def _macos_runner_option_path(command: str, option: str) -> Optional[Path]:
        try:
            # The macOS helpers normally expose POSIX paths. Keep backslashes
            # intact when tests or persisted session data contain a Windows
            # path instead of treating them as shell escapes.
            tokens = shlex.split(command, posix="\\" not in command)
        except ValueError:
            tokens = command.split()
        for index, token in enumerate(tokens):
            if token == option and index + 1 < len(tokens):
                return Path(tokens[index + 1].strip("\"'"))
            if token.startswith(f"{option}="):
                return Path(token.split("=", 1)[1].strip("\"'"))
        return None

    def _macos_runner_game_path(self, command: str) -> Optional[Path]:
        return self._macos_runner_option_path(command, "-game")

    def _macos_runner_debug_path(self, command: str) -> Optional[Path]:
        return self._macos_runner_option_path(command, "-debugoutput")

    @staticmethod
    def _new_macos_launch_token() -> str:
        """Return an unguessable marker inherited only by one owned Igor launch."""
        return secrets.token_urlsafe(32)

    def _macos_process_has_launch_token(self, pid: int, launch_token: Optional[str]) -> bool:
        """Check the live process environment for the exact per-launch ownership marker."""
        if not launch_token or platform.system() != "Darwin":
            return False
        completed = subprocess.run(
            ["ps", "eww", "-p", str(pid)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        marker = f"{self._MACOS_LAUNCH_TOKEN_ENV}={launch_token}"
        return completed.returncode == 0 and marker in completed.stdout.split()

    def _reject_foreign_igor_after_launch(self, owned_igor_pid: int) -> None:
        """Roll back if an IDE Igor won the final check-to-launch race."""
        foreign = set(self._find_active_igor_processes()) - {owned_igor_pid}
        if foreign:
            raise RuntimeError(
                "GameMaker/Igor activity started concurrently with this owned launch "
                f"(PID(s): {sorted(foreign)}). Aborting the owned launch to avoid overlap."
            )

    def _owned_macos_temp_root(self) -> Optional[Path]:
        override = getattr(self, "_macos_timeout_temp_root_override", None)
        if override is not None:
            return Path(override).resolve(strict=False)
        try:
            return (self._igor_work_root() / "temp").resolve(strict=False)
        except (AttributeError, OSError, RuntimeError, RuntimeNotFoundError):
            return None

    def _find_macos_owned_helper_pids(
        self,
        game_path: Path,
        debug_log_path: Path,
        baseline_runner_pids: set[int] | dict[int, MacOSProcess],
        baseline_tail_pids: set[int] | dict[int, MacOSProcess],
        owned_igor_pid: Optional[int],
        launch_token: Optional[str] = None,
    ) -> tuple[set[int], set[int], dict[int, MacOSProcess]]:
        """Return only new helpers attributable to one owned Igor launch."""
        processes = self._snapshot_macos_processes()
        runner_pids: set[int] = set()
        tail_pids: set[int] = set()
        for pid, process in processes.items():
            if (
                not self._matches_macos_baseline(pid, process, baseline_runner_pids)
                and "/Mac_Runner" in process.command
            ):
                if self._macos_process_has_launch_token(pid, launch_token) or (
                    owned_igor_pid is not None and self._is_descendant_of(pid, owned_igor_pid, processes)
                ):
                    runner_pids.add(pid)
            if (
                not self._matches_macos_baseline(pid, process, baseline_tail_pids)
                and "tail -F" in process.command
                and (
                    self._macos_process_has_launch_token(pid, launch_token)
                    or (owned_igor_pid is not None and self._is_descendant_of(pid, owned_igor_pid, processes))
                )
            ):
                tail_pids.add(pid)
        return runner_pids, tail_pids, processes

    @staticmethod
    def _same_macos_process_identity(current: Optional[MacOSProcess], expected: Optional[MacOSProcess]) -> bool:
        """Compare stable identity fields while allowing normal PPID reparenting."""
        return (
            current is not None
            and expected is not None
            and current.pid == expected.pid
            and current.command == expected.command
            and current.started == expected.started
        )

    def _write_macos_ownership_manifest(
        self,
        baseline_processes: dict[int, MacOSProcess],
        game_path: Path,
        debug_log_path: Path,
        launch_token: Optional[str] = None,
    ) -> None:
        """Publish the immediate pre-launch baseline for parent cleanup after worker loss."""
        raw_path = os.environ.get(self._MACOS_OWNERSHIP_MANIFEST_ENV, "").strip()
        if not raw_path:
            return
        manifest_path = Path(raw_path)
        owned_temp_root = self._owned_macos_temp_root()
        payload = {
            "project_root": str(self.project_root),
            "game_path": str(game_path),
            "debug_log_path": str(debug_log_path),
            "owned_temp_root": str(owned_temp_root) if owned_temp_root is not None else None,
            "launch_token": launch_token,
            "baseline": {
                str(pid): {
                    "pid": process.pid,
                    "ppid": process.ppid,
                    "command": process.command,
                    "started": process.started,
                }
                for pid, process in baseline_processes.items()
                if "/Mac_Runner" in process.command or "tail -F" in process.command
            },
        }
        temporary_path = manifest_path.with_suffix(f"{manifest_path.suffix}.{os.getpid()}.tmp")
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.replace(temporary_path, manifest_path)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise RuntimeError(f"Could not persist macOS runner ownership before launch: {exc}") from exc

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
        baseline_runner_pids: set[int] | dict[int, MacOSProcess],
        baseline_tail_pids: set[int] | dict[int, MacOSProcess],
        launch_token: Optional[str] = None,
        timeout_seconds: float = 120.0,
    ) -> tuple[Optional[int], set[int], set[int]]:
        """Wait for a new macOS local run helper process to appear for this project."""
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            runner_pids, tail_pids, processes = self._find_macos_owned_helper_pids(
                game_path,
                debug_log_path,
                baseline_runner_pids,
                baseline_tail_pids,
                process.pid,
                launch_token,
            )
            launch_pids = {pid for pid in runner_pids if self._macos_runner_game_path(processes[pid].command)}
            if launch_pids:
                primary_pid = max(launch_pids)
                return primary_pid, runner_pids, tail_pids
            if process.poll() is not None:
                return None, runner_pids, tail_pids
            time.sleep(0.5)

        runner_pids, tail_pids, processes = self._find_macos_owned_helper_pids(
            game_path,
            debug_log_path,
            baseline_runner_pids,
            baseline_tail_pids,
            process.pid,
            launch_token,
        )
        launch_pids = {pid for pid in runner_pids if self._macos_runner_game_path(processes[pid].command)}
        runner_pid = max(launch_pids) if launch_pids else None
        return runner_pid, runner_pids, tail_pids

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
            "cwd": str(self.project_root),
            "env": build_igor_environment(),
        }
        process_kwargs.update(self._normalize_path_for_popen())
        try:
            completed = subprocess.run(cmd, check=False, timeout=20, **process_kwargs)
        except subprocess.TimeoutExpired:
            print("[WARN] Igor Stop command timed out after 20 seconds.")
            return False

        if completed.stdout:
            for line in completed.stdout.splitlines():
                line = line.strip()
                if line:
                    print(f"   {line}")

        return completed.returncode == 0

    def _terminate_pid(self, pid: int, label: str, expected: Optional[MacOSProcess] = None) -> None:
        """Terminate a helper process, escalating to SIGKILL if needed."""
        if expected is not None and not self._same_macos_process_identity(
            self._snapshot_macos_processes().get(pid), expected
        ):
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception as exc:
            print(f"[WARN] Failed to terminate {label} process {pid}: {exc}")
            return

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if expected is not None:
                current = self._snapshot_macos_processes().get(pid)
                if current is None or not self._same_macos_process_identity(current, expected):
                    return
                time.sleep(0.2)
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.2)

        force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)

        if expected is not None and not self._same_macos_process_identity(
            self._snapshot_macos_processes().get(pid), expected
        ):
            return
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
        baseline_runner_pids: set[int] | dict[int, MacOSProcess],
        baseline_tail_pids: set[int] | dict[int, MacOSProcess],
        owned_igor_pid: Optional[int] = None,
        owned_igor_command: Optional[str] = None,
        owned_igor_started: Optional[str] = None,
        launch_token: Optional[str] = None,
        *,
        sweep_seconds: float = 0.0,
    ) -> None:
        """Remove project helpers and Igor spawned by one owned launch."""
        deadline = time.monotonic() + max(0.0, sweep_seconds)
        while True:
            runner_pids, tail_pids, processes = self._find_macos_owned_helper_pids(
                game_path,
                debug_log_path,
                baseline_runner_pids,
                baseline_tail_pids,
                owned_igor_pid,
                launch_token,
            )

            for pid in sorted(runner_pids):
                current = self._snapshot_macos_processes().get(pid)
                expected = processes.get(pid)
                if self._same_macos_process_identity(current, expected):
                    print(f"[CLEANUP] Terminating owned macOS runner PID {pid}...")
                    self._terminate_pid(pid, "runner", expected)

            for pid in sorted(tail_pids):
                current = self._snapshot_macos_processes().get(pid)
                expected = processes.get(pid)
                if self._same_macos_process_identity(current, expected):
                    print(f"[CLEANUP] Terminating owned macOS log tail PID {pid}...")
                    self._terminate_pid(pid, "tail", expected)

            if (
                owned_igor_pid is not None
                and owned_igor_command is not None
                and owned_igor_pid in processes
                and processes[owned_igor_pid].command == owned_igor_command
                and (owned_igor_started is None or processes[owned_igor_pid].started == owned_igor_started)
            ):
                current = self._snapshot_macos_processes().get(owned_igor_pid)
                expected = processes[owned_igor_pid]
                if self._same_macos_process_identity(current, expected):
                    print(f"[CLEANUP] Terminating owned Igor PID {owned_igor_pid}...")
                    self._terminate_pid(owned_igor_pid, "Igor", expected)

            if time.monotonic() >= deadline:
                return
            time.sleep(0.2)

    def _tracked_macos_helper_pids(self, session, processes: dict[int, MacOSProcess]) -> tuple[set[int], set[int]]:
        """Resolve persisted helper identities without trusting a recycled PID."""
        runner_commands = getattr(session, "macos_runner_commands", {}) or {}
        tail_commands = getattr(session, "macos_tail_commands", {}) or {}
        runner_starts = getattr(session, "macos_runner_starts", {}) or {}
        tail_starts = getattr(session, "macos_tail_starts", {}) or {}
        launch_token = getattr(session, "macos_launch_token", None)
        runner_pids: set[int] = set()
        tail_pids: set[int] = set()
        for raw_pid, command in runner_commands.items():
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                continue
            expected_started = runner_starts.get(str(raw_pid), "")
            if not isinstance(expected_started, str) or not expected_started:
                continue
            if pid in processes and processes[pid].command == command and processes[pid].started == expected_started:
                runner_pids.add(pid)
        for raw_pid, command in tail_commands.items():
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                continue
            expected_started = tail_starts.get(str(raw_pid), "")
            if not isinstance(expected_started, str) or not expected_started:
                continue
            if pid in processes and processes[pid].command == command and processes[pid].started == expected_started:
                tail_pids.add(pid)
        if isinstance(launch_token, str) and launch_token:
            for pid, process in processes.items():
                if pid in runner_pids or pid in tail_pids:
                    continue
                if "/Mac_Runner" not in process.command and "tail -F" not in process.command:
                    continue
                if not self._macos_process_has_launch_token(pid, launch_token):
                    continue
                if "/Mac_Runner" in process.command:
                    runner_pids.add(pid)
                elif "tail -F" in process.command:
                    tail_pids.add(pid)
        return runner_pids, tail_pids

    @staticmethod
    def _tracked_macos_igor_pid(session, processes: dict[int, MacOSProcess]) -> Optional[int]:
        """Resolve the owned Igor identity without trusting a recycled PID."""
        pid = getattr(session, "macos_igor_pid", None)
        command = getattr(session, "macos_igor_command", None)
        started = getattr(session, "macos_igor_started", None)
        if (
            not isinstance(pid, int)
            or pid <= 0
            or not isinstance(command, str)
            or not isinstance(started, str)
            or not started
        ):
            return None
        process = processes.get(pid)
        if process is None or process.command != command or process.started != started:
            return None
        return pid

    def _stop_macos_run_session(self, session) -> Dict[str, Any]:
        """Stop a macOS local run session tracked by the actual runner PID."""
        game_path = Path(session.exe_path)
        debug_log_path = Path(session.log_file) if session.log_file else self._macos_debug_log_path()
        processes = self._snapshot_macos_processes()
        tracked_runner_pids, tracked_tail_pids = self._tracked_macos_helper_pids(session, processes)
        tracked_igor_pid = self._tracked_macos_igor_pid(session, processes)

        print(f"[STOP] Stopping macOS local run (Runner PID: {session.pid})...")
        stop_ok = (
            self._stop_platform_process("macOS", session.runtime_type)
            if tracked_runner_pids or tracked_igor_pid is not None
            else False
        )

        deadline = time.monotonic() + 5.0
        quiet_since: Optional[float] = None
        while time.monotonic() < deadline:
            current_processes = self._snapshot_macos_processes()
            live_runner_pids, live_tail_pids = self._tracked_macos_helper_pids(session, current_processes)
            live_igor_pid = self._tracked_macos_igor_pid(session, current_processes)
            if not live_runner_pids and not live_tail_pids and live_igor_pid is None:
                now = time.monotonic()
                quiet_since = now if quiet_since is None else quiet_since
                if now - quiet_since >= 1.5:
                    self._session_manager.clear_session()
                    message = (
                        f"macOS local run (PID: {session.pid}) stopped successfully."
                        if stop_ok
                        else f"macOS local run (PID: {session.pid}) stopped after helper cleanup."
                    )
                    return {"ok": True, "message": message}
            else:
                quiet_since = None
            time.sleep(0.2)

        current_processes = self._snapshot_macos_processes()
        live_runner_pids, live_tail_pids = self._tracked_macos_helper_pids(session, current_processes)
        live_igor_pid = self._tracked_macos_igor_pid(session, current_processes)

        for pid in sorted(live_runner_pids):
            print(f"[STOP] Terminating lingering macOS runner PID {pid}...")
            self._terminate_pid(pid, "runner", current_processes.get(pid))

        for pid in sorted(live_tail_pids):
            print(f"[STOP] Terminating lingering macOS log tail PID {pid}...")
            self._terminate_pid(pid, "tail", current_processes.get(pid))

        if live_igor_pid is not None:
            print(f"[STOP] Terminating lingering owned Igor PID {live_igor_pid}...")
            self._terminate_pid(live_igor_pid, "Igor", current_processes.get(live_igor_pid))

        current_processes = self._snapshot_macos_processes()
        remaining_runner_pids, remaining_tail_pids = self._tracked_macos_helper_pids(session, current_processes)
        remaining_igor_pid = self._tracked_macos_igor_pid(session, current_processes)
        self._session_manager.clear_session()

        if remaining_runner_pids or remaining_tail_pids or remaining_igor_pid is not None:
            return {
                "ok": False,
                "message": (
                    "Failed to stop macOS local run completely. "
                    f"Runner PIDs still alive: {sorted(remaining_runner_pids)}; "
                    f"log tail PIDs still alive: {sorted(remaining_tail_pids)}; "
                    f"Igor PID still alive: {remaining_igor_pid}"
                ),
            }

        message = (
            f"macOS local run (PID: {session.pid}) stopped successfully."
            if stop_ok
            else f"macOS local run (PID: {session.pid}) stopped after manual cleanup."
        )
        return {"ok": True, "message": message}
