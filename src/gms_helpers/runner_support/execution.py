from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..gamemaker_machine_lock import GameMakerMachineLock
from .targets import ensure_igor_supported_runtime_type, normalize_platform_target


class RunnerExecutionMixin:
    def run_project_direct(
        self, platform_target: Optional[str] = None, runtime_type="VM", background=False, output_location="temp"
    ):
        """
        Run the project directly.

        Args:
            platform_target: Target platform (default: host OS)
            runtime_type: Runtime type VM or YYC (default: VM); GMS2 VM/YYC aliases are accepted
            background: Run in background (default: False)
            output_location: Where to output files - 'temp' (IDE-style, AppData) or 'project' (classic output folder)
        """
        platform_target = normalize_platform_target(platform_target)
        runtime_type = ensure_igor_supported_runtime_type(runtime_type)
        attempt_limit = self._infrastructure_attempt_limit()
        self.infrastructure_attempt_count = 0
        self.retried_infrastructure_failure = False
        for attempt in range(1, attempt_limit + 1):
            self.infrastructure_attempt_count = attempt
            if platform_target == "macOS":
                print("[RUN] macOS local runs use Igor Run to match IDE behavior and avoid package signing.")
                result = self._run_project_classic_approach(platform_target, runtime_type, background)
            elif output_location == "temp":
                result = self._run_project_ide_temp_approach(platform_target, runtime_type, background)
            else:  # output_location == "project"
                result = self._run_project_classic_approach(platform_target, runtime_type, background)

            succeeded = result if isinstance(result, bool) else isinstance(result, dict) and result.get("ok") is True
            if succeeded or self.last_failure_retryable is not True or attempt >= attempt_limit:
                if isinstance(result, dict):
                    result.setdefault("infrastructure_attempt_count", attempt)
                    result.setdefault("retried_infrastructure_failure", self.retried_infrastructure_failure)
                return result
            self.retried_infrastructure_failure = True
            try:
                self._reset_igor_transient_state()
            except OSError as exc:
                message = f"Could not clear GameMaker transient state before retry: {exc}"
                self._remember_failure(message)
                print(f"[ERROR] {message}")
                if isinstance(result, dict):
                    result["ok"] = False
                    result["message"] = message
                return result
            print(
                f"[RETRY] GameMaker runtime infrastructure abort on attempt {attempt}/{attempt_limit}; "
                "cleared transient state and retrying."
            )

        return False

    def _run_project_ide_temp_approach(self, platform_target="Windows", runtime_type="VM", background=False):
        """
        Run the project using IDE-temp approach:
        1. Package to zip in IDE temp directory
        2. Extract zip contents
        3. Run the generated game artifact from the temp location
        """
        platform_target = normalize_platform_target(platform_target)
        machine_lock = GameMakerMachineLock("run-start", self.project_root)

        try:
            machine_lock.acquire()
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
            extra_args = [f"/of={ide_temp_dir / project_name}"]
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
                self._remember_failure(
                    failure_message,
                    retryable=self._is_retryable_igor_failure(process.returncode, output_lines),
                )
                print(f"[ERROR] {failure_message}")
                print(f"[ERROR] Launch target not found in: {ide_temp_dir}")
                print("Available files:")
                for file in sorted(ide_temp_dir.iterdir()):
                    print(f"  - {file.name}")
                return False

            print(f"[OK] Game packaged successfully: {launch_path}")

            # Step 3: Run the game binary directly.
            print("[RUN] Starting game...")

            self.game_process = self._start_game_process(launch_path)

            print(f"[OK] Game started! PID: {self.game_process.pid}")

            # Create a persistent session so stop/status can find this process later
            session = self._session_manager.create_session(
                pid=self.game_process.pid,
                exe_path=str(launch_path),
                platform_target=platform_target,
                runtime_type=runtime_type,
            )
            machine_lock.release()

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
            print(f"[ERROR] Game exited with code {self.game_process.returncode}")
            return False

        except Exception as e:
            self._remember_failure(str(e))
            print(f"[ERROR] Error running project: {e}")
            return False
        finally:
            machine_lock.release()

    def _run_project_classic_approach(self, platform_target="Windows", runtime_type="VM", background=False):
        """
        Run the project using the classic approach:
        1. Use Igor Run command (creates output folder in project directory)
        2. Game runs directly from Igor
        """
        platform_target = normalize_platform_target(platform_target)
        machine_lock = GameMakerMachineLock("run-start", self.project_root)

        try:
            machine_lock.acquire()
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
            track_macos_runner = platform_target == "macOS"
            if track_macos_runner:
                macos_debug_log = self._macos_debug_log_path()
                macos_game_path = self.project_root / "output" / project_name / "game.ios"
                baseline_runner_pids, baseline_tail_pids = self._find_macos_validation_helper_pids(
                    macos_game_path,
                    macos_debug_log,
                )

            # Run the game using Igor Run command
            self.game_process = self._run_igor_command(cmd)
            session_kwargs = {
                "pid": self.game_process.pid,
                "exe_path": str(project_file),
                "platform_target": platform_target,
                "runtime_type": runtime_type,
            }

            if track_macos_runner and macos_game_path and macos_debug_log:
                output_lines, output_thread = self._collect_igor_output_async(
                    self.game_process,
                    "local run",
                    emit_output=not background,
                )
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
                    self._remember_failure(
                        failure_message,
                        retryable=self._is_retryable_igor_failure(
                            self.game_process.returncode,
                            output_lines,
                        ),
                    )
                    print(f"[ERROR] {failure_message}")
                    if background:
                        return {
                            "ok": False,
                            "background": True,
                            "message": failure_message,
                        }
                    return False

                session_kwargs.update(
                    {
                        "pid": runner_pid,
                        "exe_path": str(macos_game_path),
                        "log_file": str(macos_debug_log),
                    }
                )

            session = self._session_manager.create_session(**session_kwargs)
            machine_lock.release()

            if background:
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

            # Foreground mode: stream output and wait
            if not track_macos_runner:
                output_lines = self._stream_igor_output(self.game_process, "local run")

            self.game_process.wait()
            if output_thread is not None:
                output_thread.join(timeout=5)

            # Clean up session after game exits
            self._session_manager.clear_session()

            if self.game_process.returncode == 0:
                print("[OK] Game finished successfully!")
                return True

            failure_message = self._build_stage_failure_message(
                "local run",
                self.game_process.returncode,
                output_lines,
            )
            self._remember_failure(
                failure_message,
                retryable=self._is_retryable_igor_failure(self.game_process.returncode, output_lines),
            )
            print(f"[ERROR] {failure_message}")
            return False

        except Exception as e:
            self._remember_failure(str(e))
            print(f"[ERROR] Error running project: {e}")
            return False
        finally:
            machine_lock.release()

    def stop_game(self) -> Dict[str, Any]:
        """
        Stop the running game.

        Uses the session manager to find and stop the game process,
        even if this is a new GameMakerRunner instance.

        Returns:
            Dict with result of stop operation
        """
        session = self._session_manager.get_current_session()
        if (
            session
            and session.platform_target == "macOS"
            and session.log_file
            and session.exe_path.endswith("game.ios")
        ):
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
