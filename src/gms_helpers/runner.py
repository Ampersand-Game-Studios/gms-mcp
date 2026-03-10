#!/usr/bin/env python3
"""
GameMaker Runner Module
Provides functionality to compile and run GameMaker projects using Igor
"""

import errno
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

# Direct imports - no complex fallbacks needed
from .utils import find_yyp
from .exceptions import RuntimeNotFoundError, LicenseNotFoundError
from .runtime_manager import RuntimeManager
from .run_session import RunSessionManager, get_session_manager


def detect_default_target_platform() -> str:
    """Map host OS to the matching GameMaker target platform name."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Linux":
        return "Linux"
    return "Windows"


def normalize_platform_target(platform_target: Optional[str]) -> str:
    """Normalize user input and provide an OS-appropriate default."""
    if not platform_target:
        return detect_default_target_platform()

    aliases = {
        "windows": "Windows",
        "html5": "HTML5",
        "macos": "macOS",
        "mac": "macOS",
        "osx": "macOS",
        "linux": "Linux",
        "android": "Android",
        "ios": "iOS",
    }
    return aliases.get(platform_target.strip().lower(), platform_target)


def _to_igor_platform(platform_target: str) -> str:
    """Map canonical platform targets to the token Igor expects after `--`."""
    if platform_target == "macOS":
        return "Mac"
    return platform_target


class GameMakerRunner:
    """Handles GameMaker project compilation and execution."""
    
    def __init__(self, project_root: Path, runtime_version: Optional[str] = None):
        self.project_root = Path(project_root).resolve()
        self.runtime_version = runtime_version
        self.yyp_file = None
        self.igor_path = None
        self.runtime_path = None
        self.game_process = None
        self.last_action_label: Optional[str] = None
        self.last_failure_message: Optional[str] = None
        self._runtime_manager = RuntimeManager(self.project_root)
        self._session_manager = RunSessionManager(self.project_root)
        
    def find_project_file(self) -> Path:
        """Find the .yyp file in the project root."""
        if self.yyp_file:
            return self.yyp_file
            
        # First try the current directory
        try:
            self.yyp_file = find_yyp(self.project_root)
            return self.yyp_file
        except SystemExit:
            pass
        
        # If not found, check if we're in root and need to look in gamemaker/ subdirectory
        gamemaker_subdir = self.project_root / "gamemaker"
        if gamemaker_subdir.exists() and gamemaker_subdir.is_dir():
            try:
                self.yyp_file = find_yyp(gamemaker_subdir)
                # Update project_root to point to gamemaker directory
                self.project_root = gamemaker_subdir
                return self.yyp_file
            except SystemExit:
                pass
        
        raise FileNotFoundError(f"No .yyp file found in {self.project_root} or {self.project_root}/gamemaker")
    
    def find_gamemaker_runtime(self) -> Optional[Path]:
        """Locate GameMaker runtime and Igor binary using RuntimeManager."""
        if self.igor_path:
            return self.igor_path
            
        runtime_info = self._runtime_manager.select(self.runtime_version)
        if runtime_info and runtime_info.is_valid:
            self.igor_path = Path(runtime_info.igor_path)
            self.runtime_path = Path(runtime_info.path)
            return self.igor_path
            
        return None

    def get_prefabs_path(self) -> Optional[Path]:
        """
        Get the path to the GameMaker prefabs library.

        Prefabs are required for projects that use ForcedPrefabProjectReferences.
        The path can be configured via:
        1. GMS_PREFABS_PATH environment variable
        2. Auto-detected from ProgramData (Windows) or standard locations

        Returns:
            Path to prefabs folder, or None if not found
        """
        # Check environment variable first
        env_path = os.environ.get("GMS_PREFABS_PATH")
        if env_path:
            prefabs_path = Path(env_path)
            if prefabs_path.exists():
                return prefabs_path

        system = platform.system()

        if system == "Windows":
            # Default Windows location
            default_paths = [
                Path("C:/ProgramData/GameMakerStudio2/Prefabs"),
                Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "GameMakerStudio2" / "Prefabs",
            ]
        elif system == "Darwin":
            # macOS location
            default_paths = [
                Path("/Users/Shared/GameMakerStudio2/Prefabs"),
                Path("/Library/Application Support/GameMakerStudio2/Prefabs"),
                Path.home() / "Library/Application Support/GameMakerStudio2/Prefabs",
            ]
        else:
            # Linux location
            default_paths = [
                Path.home() / ".config/GameMakerStudio2/Prefabs",
                Path("/opt/GameMakerStudio2/Prefabs"),
            ]

        for path in default_paths:
            if path.exists():
                return path

        return None

    def find_license_file(self) -> Optional[Path]:
        """Find GameMaker license file."""
        valid_filenames = ("license.plist", "licence.plist")

        def _find_in_directory(search_root: Path) -> Optional[Path]:
            if not search_root.is_dir():
                return None

            for filename in valid_filenames:
                direct_match = search_root / filename
                if direct_match.exists():
                    return direct_match

            matches = []
            for filename in valid_filenames:
                matches.extend(search_root.rglob(filename))

            if not matches:
                return None

            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return matches[0]

        system = platform.system()
        
        if system == "Windows":
            base_paths = [
                Path.home() / "AppData/Roaming/GameMakerStudio2",
                Path("C:/Users") / os.getenv("USERNAME", "") / "AppData/Roaming/GameMakerStudio2"
            ]
        elif system == "Darwin":
            base_paths = [
                Path.home() / "Library/Application Support/GameMakerStudio2",
                Path("/Library/Application Support/GameMakerStudio2"),
                Path("/Users/Shared/GameMakerStudio2"),
            ]
        else:  # Linux
            base_paths = [
                Path.home() / ".config/GameMakerStudio2"
            ]
        
        for base_path in base_paths:
            if not base_path.exists():
                continue
                
            # Look for user directories (usually username_number format)
            user_dirs = [d for d in base_path.iterdir() if d.is_dir()]
            
            for user_dir in user_dirs:
                license_file = _find_in_directory(user_dir)
                if license_file:
                    return license_file

            # Some installs store licence directly under the base path or nested subfolder.
            license_file = _find_in_directory(base_path)
            if license_file:
                return license_file
        
        return None

    def _normalize_path_for_popen(self) -> dict:
        """Return platform-safe keyword args for launching subprocesses."""
        process_kwargs = {}
        if platform.system() != "Windows":
            process_kwargs["start_new_session"] = True

        return process_kwargs

    def _build_macos_launch_guidance(self, launch_target: Path, error: OSError, action: str) -> str:
        """Build a remediation message for macOS launch/runtime permission issues."""
        errno_value = getattr(error, "errno", None)
        error_text = str(error).lower()
        action_name = {
            "game": "Game launch",
            "runtime": "Runtime execution",
        }.get(action, "Subprocess")

        guidance = [
            "- Verify execute permission is set on the file (`chmod +x`).",
            "- If the file was downloaded, clear quarantine metadata (`xattr -dr com.apple.quarantine \"<path>\"`).",
            "- Reinstall or trust the GameMaker runtime if the binary is unsigned.",
            "- Try running from an accessible folder and avoid macOS protected paths.",
        ]
        remediation = "\n".join(f"  {line}" for line in guidance)

        if errno_value in (errno.EACCES, errno.EPERM) or "permission denied" in error_text:
            return (
                f"{action_name} failed due to a macOS permission/sandbox restriction.\n"
                f"Path: {launch_target}\n"
                f"Suggested fix:\n{remediation}"
            )

        if "operation not permitted" in error_text or "sandbox" in error_text:
            return (
                f"{action_name} was blocked by macOS sandbox rules.\n"
                f"Path: {launch_target}\n"
                f"Remediation:\n{remediation}"
            )

        if "code signature" in error_text or "codesign" in error_text:
            return (
                f"{action_name} was blocked by macOS code signing enforcement.\n"
                f"Path: {launch_target}\n"
                f"Remediation:\n{remediation}"
            )

        return f"{action_name} failed for macOS with: {error}"

    def _start_game_process(self, launch_path: Path) -> subprocess.Popen:
        """Start a game process with OS-appropriate process-group settings."""
        try:
            return subprocess.Popen(
                [str(launch_path)],
                **self._normalize_path_for_popen()
            )
        except OSError as exc:
            if platform.system() == "Darwin":
                raise RuntimeError(self._build_macos_launch_guidance(launch_path, exc, "game")) from exc
            raise

    def _run_igor_command(self, cmd: List[str]) -> subprocess.Popen:
        """Start an Igor command with shared process settings."""
        process_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True, "bufsize": 1, "universal_newlines": True}
        process_kwargs.update(self._normalize_path_for_popen())
        try:
            return subprocess.Popen(cmd, **process_kwargs)
        except OSError as exc:
            if platform.system() == "Darwin":
                igor_path = Path(cmd[0]) if cmd else None
                raise RuntimeError(
                    self._build_macos_launch_guidance(
                        igor_path or Path("<unknown>"),
                        exc,
                        "runtime",
                    )
                ) from exc
            raise
    
    def _find_macos_app_binary(self, app_bundle: Path) -> Optional[Path]:
        """Return the first executable inside a macOS .app bundle."""
        macos_dir = app_bundle / "Contents" / "MacOS"
        if not macos_dir.exists() or not macos_dir.is_dir():
            return None

        for candidate in sorted(macos_dir.iterdir()):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
        return None

    def _find_launch_target(self, build_dir: Path, project_name: str, platform_target: str) -> Optional[Path]:
        """Locate a runnable output artifact for the selected platform."""
        target = normalize_platform_target(platform_target)

        if target == "Windows":
            candidates = [
                build_dir / f"{project_name}.exe",
                build_dir / "template.exe",
                build_dir / "runner.exe",
            ]
            for candidate in candidates:
                if candidate.exists() and candidate.is_file():
                    return candidate
            return None

        if target == "macOS":
            app_candidates = [
                build_dir / f"{project_name}.app",
                build_dir / "Mac_Runner.app",
                build_dir / "Runner.app",
            ]
            for app_candidate in app_candidates:
                exe_path = self._find_macos_app_binary(app_candidate)
                if exe_path:
                    return exe_path

            for app_candidate in sorted(build_dir.glob("*.app")):
                exe_path = self._find_macos_app_binary(app_candidate)
                if exe_path:
                    return exe_path
            return None

        candidates = [
            build_dir / project_name,
            build_dir / "runner",
            build_dir / "Runner",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        for candidate in sorted(build_dir.iterdir()):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate

        return None

    def _clear_last_result(self, action_label: str) -> None:
        """Reset the remembered result state for a new runner action."""
        self.last_action_label = action_label
        self.last_failure_message = None

    def _remember_failure(self, message: str) -> None:
        """Store the most recent runner failure for command wrappers."""
        self.last_failure_message = message

    def _system_temp_root(self) -> Path:
        """Return the system temp directory used for Igor cache/temp folders."""
        import tempfile

        return Path(tempfile.gettempdir())

    def _append_runtime_type_arg(self, cmd: List[str], runtime_type: str) -> None:
        """Append the YYC runtime switch when requested."""
        if runtime_type.upper() == "YYC":
            cmd.append("/runtime=YYC")

    def _build_igor_base_command(self) -> List[str]:
        """Build the shared Igor argument prefix used by compile/run commands."""
        igor_path = self.find_gamemaker_runtime()
        if not igor_path or not self.runtime_path:
            raise RuntimeNotFoundError("GameMaker runtime not found. Please install GameMaker Studio.")

        project_file = self.find_project_file()
        license_file = self.find_license_file()
        if not license_file:
            raise LicenseNotFoundError("GameMaker license file not found. Please log into GameMaker IDE first.")

        system_temp = self._system_temp_root()
        cache_dir = system_temp / "gms_cache"
        temp_dir = system_temp / "gms_temp"

        cmd = [str(igor_path)]
        cmd.extend([f"/lf={license_file}"])
        cmd.extend([f"/rp={self.runtime_path}"])
        cmd.extend([f"/project={project_file}"])
        cmd.extend([f"/cache={cache_dir}"])
        cmd.extend([f"/temp={temp_dir}"])

        prefabs_path = self.get_prefabs_path()
        if prefabs_path:
            cmd.extend([f"--pf={prefabs_path}"])

        return cmd

    def _build_platform_action_command(
        self,
        action: str,
        platform_target: Optional[str] = None,
        runtime_type: str = "VM",
        extra_args: Optional[List[str]] = None,
    ) -> List[str]:
        """Build a normal Igor `-- <platform> <action>` command."""
        platform_target = normalize_platform_target(platform_target)
        igor_platform = _to_igor_platform(platform_target)

        cmd = self._build_igor_base_command()
        if extra_args:
            cmd.extend(extra_args)
        self._append_runtime_type_arg(cmd, runtime_type)
        cmd.extend(["--", igor_platform, action])
        return cmd

    def _stream_igor_output(self, process: subprocess.Popen, stage_label: str) -> List[str]:
        """Stream Igor stdout while lightly classifying lines for humans."""
        output_lines: List[str] = []

        if not process.stdout:
            return output_lines

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            output_lines.append(line)
            lowered = line.lower()
            if "error" in lowered:
                print(f"[ERROR] {line}")
            elif "warning" in lowered:
                print(f"[WARN] {line}")
            elif "compile" in lowered or "build" in lowered:
                print(f"[BUILD] {line}")
            elif stage_label == "package/export" and (
                "package" in lowered or "sign" in lowered or "zip" in lowered or "export" in lowered
            ):
                print(f"[PACKAGE] {line}")
            elif stage_label == "local compile validation" and "test" in lowered:
                print(f"[TEST] {line}")
            else:
                print(f"   {line}")

        return output_lines

    def _is_macos_signing_failure(self, output_lines: List[str]) -> bool:
        """Best-effort detection for macOS signing/certificate failures."""
        markers = (
            "could not find matching certificate for developer id application",
            "option_mac_signing_identity",
            "seckeychainunlock",
            "createmacexecutable",
            "unable to obtain authorization for this operation",
            "codesign",
        )
        lowered_lines = [line.lower() for line in output_lines]
        return any(any(marker in line for marker in markers) for line in lowered_lines)

    def _build_stage_failure_message(self, stage_label: str, returncode: int, output_lines: List[str]) -> str:
        """Build a stage-aware failure summary instead of a generic compile error."""
        if stage_label == "package/export":
            if self._is_macos_signing_failure(output_lines):
                return (
                    "Package/export step failed during macOS signing or certificate selection. "
                    "Igor reached packaging; this is not a source compile failure."
                )
            return f"Package/export step failed with exit code {returncode}."
        if stage_label == "local compile validation":
            return f"Local compile validation failed with exit code {returncode}."
        if stage_label == "local run":
            return f"Local run failed with exit code {returncode}."
        return f"{stage_label.capitalize()} failed with exit code {returncode}."

    def _collect_igor_output_async(self, process: subprocess.Popen, stage_label: str) -> tuple[List[str], threading.Thread]:
        """Stream Igor output in a background thread while the caller polls side effects."""
        output_lines: List[str] = []

        def _reader() -> None:
            output_lines.extend(self._stream_igor_output(process, stage_label))

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        return output_lines, thread

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

    def _build_macos_compile_validation_command(self, runtime_type: str) -> List[str]:
        """
        Build the macOS compile-validation command.

        Igor exposes local `Run` and packaging/export actions on macOS, but not a pure
        compile-only local build mode. For local validation we use `Run`, wait until the
        runner reaches the game main loop, then issue `Stop`.
        """
        return self._build_platform_action_command("Run", "macOS", runtime_type)

    def build_igor_command(self, action: str = "Run", platform_target: Optional[str] = None,
                          runtime_type: str = "VM", **kwargs) -> List[str]:
        """Build Igor command line."""
        return self._build_platform_action_command(action, platform_target, runtime_type)
    
    def compile_project(self, platform_target: Optional[str] = None, runtime_type: str = "VM") -> bool:
        """Compile the GameMaker project."""
        platform_target = normalize_platform_target(platform_target)

        try:
            print(f"[BUILD] Compiling project for {platform_target} ({runtime_type})...")

            if platform_target == "macOS":
                self._clear_last_result("local compile validation")
                cmd = self._build_macos_compile_validation_command(runtime_type)
                print("[BUILD] Using bounded Igor local run validation on macOS to avoid package signing.")
                print(f"[CMD] Validation command: {' '.join(cmd)}")
                project_name = self.find_project_file().stem
                debug_log = self._macos_debug_log_path()
                game_path = self.project_root / "output" / project_name / "game.ios"
                start_offset = debug_log.stat().st_size if debug_log.exists() else 0
                baseline_runner_pids, baseline_tail_pids = self._find_macos_validation_helper_pids(game_path, debug_log)
                output_lines: List[str] = []
                output_thread: Optional[threading.Thread] = None
                process = None
                reached_main_loop = False
                timed_out = False
                try:
                    process = self._run_igor_command(cmd)
                    output_lines, output_thread = self._collect_igor_output_async(process, "local compile validation")
                    reached_main_loop = self._wait_for_macos_main_loop(process, debug_log, start_offset, timeout_seconds=90.0)
                    timed_out = (not reached_main_loop) and process.poll() is None
                finally:
                    if process is not None and process.poll() is None:
                        print("[BUILD] Stopping macOS local validation run...")
                        stop_ok = self._stop_platform_process("macOS", runtime_type)
                        if not stop_ok:
                            print("[WARN] Igor Stop command did not report success; terminating validation process directly.")
                            process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)

                    if output_thread is not None:
                        output_thread.join(timeout=5)

                    self._cleanup_macos_validation_helpers(
                        game_path,
                        debug_log,
                        baseline_runner_pids,
                        baseline_tail_pids,
                    )

                if reached_main_loop:
                    print("[OK] Local compile validation reached the game main loop successfully!")
                    return True

                if timed_out:
                    failure_message = "Local compile validation timed out before the game reached the main loop."
                elif process is not None and process.returncode == 0:
                    failure_message = "Local compile validation exited before the game reached the main loop."
                else:
                    return_code = process.returncode if process is not None else -1
                    failure_message = self._build_stage_failure_message(
                        "local compile validation",
                        return_code,
                        output_lines,
                    )
                self._remember_failure(failure_message)
                print(f"[ERROR] {failure_message}")
                return False

            self._clear_last_result("package/export")
            project_file = self.find_project_file()
            system_temp = self._system_temp_root()
            project_name = project_file.stem
            ide_temp_dir = system_temp / "GameMakerStudio2" / project_name
            ide_temp_dir.mkdir(parents=True, exist_ok=True)

            cmd = self._build_platform_action_command(
                "PackageZip",
                platform_target,
                runtime_type,
                extra_args=[f"--of={ide_temp_dir / project_name}"],
            )
            print(f"[CMD] Package command: {' '.join(cmd)}")

            process = self._run_igor_command(cmd)
            output_lines = self._stream_igor_output(process, "package/export")
            process.wait()

            if process.returncode == 0:
                print("[OK] Package/export completed successfully!")
                return True

            failure_message = self._build_stage_failure_message(
                "package/export",
                process.returncode,
                output_lines,
            )
            self._remember_failure(failure_message)
            print(f"[ERROR] {failure_message}")
            return False
                
        except Exception as e:
            self._remember_failure(str(e))
            print(f"[ERROR] Compilation error: {e}")
            return False
    
    def run_project_direct(self, platform_target: Optional[str] = None, runtime_type="VM", background=False, output_location="temp"):
        """
        Run the project directly.
        
        Args:
            platform_target: Target platform (default: host OS)
            runtime_type: Runtime type VM or YYC (default: VM)
            background: Run in background (default: False)
            output_location: Where to output files - 'temp' (IDE-style, AppData) or 'project' (classic output folder)
        """
        platform_target = normalize_platform_target(platform_target)

        if platform_target == "macOS":
            print("[RUN] macOS local runs use Igor Run to match IDE behavior and avoid package signing.")
            return self._run_project_classic_approach(platform_target, runtime_type, background)

        if output_location == "temp":
            return self._run_project_ide_temp_approach(platform_target, runtime_type, background)
        else:  # output_location == "project"
            return self._run_project_classic_approach(platform_target, runtime_type, background)
    
    def _run_project_ide_temp_approach(self, platform_target="Windows", runtime_type="VM", background=False):
        """
        Run the project using IDE-temp approach:
        1. Package to zip in IDE temp directory
        2. Extract zip contents
        3. Run the generated game artifact from the temp location
        """
        platform_target = normalize_platform_target(platform_target)

        try:
            import os
            import subprocess
            
            print("[RUN] Starting game using IDE-temp approach...")
            self._clear_last_result("package/export")
            
            # Step 1: Build PackageZip command to compile to IDE temp directory
            print("[PACKAGE] Packaging project to IDE temp directory...")
            
            project_file = self.find_project_file()
            system_temp = self._system_temp_root()
            project_name = project_file.stem
            
            # Use IDE temp directory structure
            ide_temp_dir = system_temp / "GameMakerStudio2" / project_name
            ide_temp_dir.mkdir(parents=True, exist_ok=True)

            target_app_zip = None
            extra_args = [f"--of={ide_temp_dir / project_name}"]
            if platform_target == "macOS":
                target_app_zip = ide_temp_dir / f"{project_name}.app.zip"
                extra_args.append(f"--tf={target_app_zip}")

            cmd = self._build_platform_action_command(
                "PackageZip",
                platform_target,
                runtime_type,
                extra_args=extra_args,
            )
            
            print(f"[CMD] Package command: {' '.join(cmd)}")
            
            # Run packaging
            process = self._run_igor_command(cmd)
            
            # Stream compilation output
            output_lines = self._stream_igor_output(process, "package/export")
            
            process.wait()
            
            # PackageZip might fail at the end when trying to create zip, but executable creation usually succeeds
            if process.returncode != 0:
                failure_message = self._build_stage_failure_message(
                    "package/export",
                    process.returncode,
                    output_lines,
                )
                print(f"[WARN] {failure_message} Checking whether runnable output was still created...")
                # Don't return False immediately - check if files were created successfully

            if platform_target == "macOS" and target_app_zip and target_app_zip.exists():
                # Igor emits a zipped .app. Extract it so we can launch the bundle directly.
                subprocess.run(
                    ["/usr/bin/unzip", "-o", str(target_app_zip), "-d", str(ide_temp_dir)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            
            # Step 2: Find the runnable artifact from PackageZip output.
            launch_path = self._find_launch_target(ide_temp_dir, project_name, platform_target)

            if not launch_path:
                failure_message = (
                    "Package/export step failed to produce a runnable local artifact."
                    if process.returncode != 0
                    else "Launch target not found after package/export completed."
                )
                self._remember_failure(failure_message)
                print(f"[ERROR] {failure_message}")
                print(f"[ERROR] Launch target not found in: {ide_temp_dir}")
                print("Available files:")
                for file in sorted(ide_temp_dir.iterdir()):
                    print(f"  - {file.name}")
                return False
                
            print(f"[OK] Game packaged successfully: {launch_path}")
            
            # Step 3: Run the game binary directly.
            print("[RUN] Starting game...")
            
            # Change to the game directory and run the executable
            original_cwd = os.getcwd()
            try:
                os.chdir(ide_temp_dir)
                
                self.game_process = self._start_game_process(launch_path)
                
                print(f"[OK] Game started! PID: {self.game_process.pid}")
                
                # Create a persistent session so stop/status can find this process later
                session = self._session_manager.create_session(
                    pid=self.game_process.pid,
                    exe_path=str(launch_path),
                    platform_target=platform_target,
                    runtime_type=runtime_type,
                )
                
                if background:
                    # Background mode: return immediately without waiting
                    print("[OK] Game running in background mode.")
                    print(f"   Session ID: {session.run_id}")
                    print("   Use gm_run_status to check if game is running.")
                    print("   Use gm_run_stop to stop the game.")
                    return {
                        "ok": True,
                        "background": True,
                        "pid": self.game_process.pid,
                        "run_id": session.run_id,
                        "exe_path": str(launch_path),
                        "message": f"Game started in background (PID: {self.game_process.pid})",
                    }
                
                # Foreground mode: wait for game to finish
                print("   Game is running...")
                print("   Close the game window to return to console.")
                
                self.game_process.wait()
                
                # Clean up session after game exits
                self._session_manager.clear_session()
                
                if self.game_process.returncode == 0:
                    print("[OK] Game finished successfully!")
                    return True
                else:
                    print(f"[ERROR] Game exited with code {self.game_process.returncode}")
                    return False
                    
            finally:
                os.chdir(original_cwd)
                
        except Exception as e:
            self._remember_failure(str(e))
            print(f"[ERROR] Error running project: {e}")
            return False
    
    def _run_project_classic_approach(self, platform_target="Windows", runtime_type="VM", background=False):
        """
        Run the project using the classic approach:
        1. Use Igor Run command (creates output folder in project directory)
        2. Game runs directly from Igor
        """
        platform_target = normalize_platform_target(platform_target)

        try:
            print("[RUN] Starting game using classic approach...")
            self._clear_last_result("local run")
            
            cmd = self._build_platform_action_command("Run", platform_target, runtime_type)
            
            print(f"[CMD] Run command: {' '.join(cmd)}")
            
            project_file = self.find_project_file()
            project_name = project_file.stem
            macos_debug_log: Optional[Path] = None
            macos_game_path: Optional[Path] = None
            baseline_runner_pids: set[int] = set()
            baseline_tail_pids: set[int] = set()
            output_lines: List[str] = []
            output_thread: Optional[threading.Thread] = None
            track_macos_runner = background and platform_target == "macOS"
            if track_macos_runner:
                macos_debug_log = self._macos_debug_log_path()
                macos_game_path = self.project_root / "output" / project_name / "game.ios"
                baseline_runner_pids, baseline_tail_pids = self._find_macos_validation_helper_pids(
                    macos_game_path,
                    macos_debug_log,
                )

            # Run the game using Igor Run command
            self.game_process = self._run_igor_command(cmd)

            if background:
                session_kwargs = {
                    "pid": self.game_process.pid,
                    "exe_path": str(project_file),
                    "platform_target": platform_target,
                    "runtime_type": runtime_type,
                }

                if track_macos_runner and macos_game_path and macos_debug_log:
                    output_lines, output_thread = self._collect_igor_output_async(self.game_process, "local run")
                    runner_pid, _runner_pids, _tail_pids = self._wait_for_macos_runner_start(
                        self.game_process,
                        macos_game_path,
                        macos_debug_log,
                        baseline_runner_pids,
                        baseline_tail_pids,
                    )
                    if self.game_process.poll() is not None and output_thread is not None:
                        output_thread.join(timeout=5)

                    if runner_pid is None:
                        if self.game_process.poll() is None:
                            self.game_process.terminate()
                            try:
                                self.game_process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                self.game_process.kill()
                                self.game_process.wait(timeout=5)
                            failure_message = "Local run timed out before macOS launched the runner process."
                        else:
                            failure_message = self._build_stage_failure_message(
                                "local run",
                                self.game_process.returncode,
                                output_lines,
                            )
                        self._remember_failure(failure_message)
                        print(f"[ERROR] {failure_message}")
                        return {
                            "ok": False,
                            "background": True,
                            "message": failure_message,
                        }

                    session_kwargs.update(
                        {
                            "pid": runner_pid,
                            "exe_path": str(macos_game_path),
                            "log_file": str(macos_debug_log),
                        }
                    )

                session = self._session_manager.create_session(**session_kwargs)
                print(f"[OK] Game started in background mode (PID: {session_kwargs['pid']})")
                print(f"   Session ID: {session.run_id}")
                print("   Use gm_run_status to check if game is running.")
                print("   Use gm_run_stop to stop the game.")
                result = {
                    "ok": True,
                    "background": True,
                    "pid": session_kwargs["pid"],
                    "run_id": session.run_id,
                    "message": f"Game started in background (PID: {session_kwargs['pid']})",
                }
                if track_macos_runner:
                    result["igor_pid"] = self.game_process.pid
                return result

            # Create a persistent session so stop/status can find this process later
            session = self._session_manager.create_session(
                pid=self.game_process.pid,
                exe_path=str(project_file),  # For classic approach, we use project file as reference
                platform_target=platform_target,
                runtime_type=runtime_type,
            )
            
            # Foreground mode: stream output and wait
            if self.game_process.stdout:
                for line in self.game_process.stdout:
                    line = line.strip()
                    if line:
                        # Basic log filtering
                        if "error" in line.lower():
                            print(f"[ERROR] {line}")
                        elif "warning" in line.lower():
                            print(f"[WARN] {line}")
                        elif "compile" in line.lower() or "build" in line.lower():
                            print(f"[BUILD] {line}")
                        else:
                            print(f"   {line}")
            
            self.game_process.wait()
            
            # Clean up session after game exits
            self._session_manager.clear_session()
            
            if self.game_process.returncode == 0:
                print("[OK] Game finished successfully!")
                return True

            failure_message = self._build_stage_failure_message(
                "local run",
                self.game_process.returncode,
                [],
            )
            self._remember_failure(failure_message)
            print(f"[ERROR] {failure_message}")
            return False
                 
        except Exception as e:
            self._remember_failure(str(e))
            print(f"[ERROR] Error running project: {e}")
            return False
    
    def stop_game(self) -> Dict[str, Any]:
        """
        Stop the running game.
        
        Uses the session manager to find and stop the game process,
        even if this is a new GameMakerRunner instance.
        
        Returns:
            Dict with result of stop operation
        """
        session = self._session_manager.get_current_session()
        if session and session.platform_target == "macOS" and session.log_file and session.exe_path.endswith("game.ios"):
            result = self._stop_macos_run_session(session)
        else:
            # First, try to use the session manager (works across instances)
            result = self._session_manager.stop_game()
        
        # Also clean up our local reference if we have one
        if self.game_process is not None:
            try:
                if self.game_process.poll() is None:
                    self.game_process.terminate()
                    try:
                        self.game_process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.game_process.kill()
            except Exception:
                pass
            self.game_process = None
        
        return result
    
    def is_game_running(self) -> bool:
        """
        Check if game is currently running.
        
        Uses the session manager to check, even if this is a new
        GameMakerRunner instance.
        
        Returns:
            True if game is running, False otherwise
        """
        status = self._session_manager.get_session_status()
        return status.get("running", False)
    
    def get_game_status(self) -> Dict[str, Any]:
        """
        Get detailed status of the running game.
        
        Returns:
            Dict with session info and running status
        """
        return self._session_manager.get_session_status()


# Convenience functions for command-line usage
def compile_project(project_root: str = ".", platform: Optional[str] = None,
                   runtime: str = "VM", runtime_version: Optional[str] = None) -> bool:
    """Compile GameMaker project."""
    runner = GameMakerRunner(Path(project_root), runtime_version=runtime_version)
    return runner.compile_project(platform, runtime)


def run_project(project_root: str = ".", platform: Optional[str] = None,
               runtime: str = "VM", background: bool = False, output_location: str = "temp",
               runtime_version: Optional[str] = None):
    """
    Run GameMaker project directly (like IDE does).
    
    Args:
        project_root: Path to project root
        platform: Target platform (default: host OS)
        runtime: Runtime type VM or YYC (default: VM)
        background: If True, return immediately without waiting for game to exit
        output_location: 'temp' (IDE-style) or 'project' (classic output folder)
        runtime_version: Specific runtime version to use
        
    Returns:
        If background=False: bool (True if game exited successfully)
        If background=True: dict with session info (pid, run_id, etc.)
    """
    runner = GameMakerRunner(Path(project_root), runtime_version=runtime_version)
    return runner.run_project_direct(platform, runtime, background, output_location)


def stop_project(project_root: str = ".") -> Dict[str, Any]:
    """
    Stop running GameMaker project.
    
    Uses persistent session tracking to find and stop the game,
    even if called from a different process or after restart.
    
    Returns:
        Dict with result of stop operation
    """
    runner = GameMakerRunner(Path(project_root))
    return runner.stop_game()


def get_project_status(project_root: str = ".") -> Dict[str, Any]:
    """
    Get status of running GameMaker project.
    
    Uses persistent session tracking to check game status,
    even if called from a different process or after restart.
    
    Returns:
        Dict with session info and running status
    """
    runner = GameMakerRunner(Path(project_root))
    return runner.get_game_status() 
