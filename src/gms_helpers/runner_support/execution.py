from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from ..gamemaker_machine_lock import GameMakerMachineLock
from .targets import ensure_igor_supported_runtime_type, normalize_platform_target


class RunnerExecutionMixin:
    def run_project_direct(
        self,
        platform_target: Optional[str] = None,
        runtime_type="VM",
        background=False,
        output_location="temp",
        enable_bridge: bool | None = None,
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
        if platform_target == "macOS":
            self.find_project_file()
            from .. import live_session

            try:
                result = live_session.start(
                    self.project_root,
                    label="run",
                    runtime=runtime_type,
                    runtime_version=self.runtime_version,
                    connect_timeout_seconds=0.5,
                    enable_bridge=enable_bridge,
                )
                if not result.get("running"):
                    self._remember_failure(result.get("message", "Game did not start"))
                    return result if background else False
                managed = live_session.get_session(self.project_root)
                if managed is None or managed.run_id != result.get("run_id"):
                    raise live_session.LiveSessionError("The owned game session ended before it could be returned.")
                self.game_process = managed.process
                if background:
                    persisted = self._session_manager.get_current_session()
                    if persisted is None or persisted.run_id != managed.run_id:
                        raise live_session.LiveSessionError("The owned game session exited during startup.")
                    return {
                        **result,
                        "ok": True,
                        "background": True,
                        "run_id": persisted.run_id,
                        "exe_path": persisted.exe_path,
                    }
                managed.process.wait()
                # Natural-exit cleanup may already have released this project's
                # lease and allowed a replacement session. Clean only our handle.
                live_session._cleanup(managed)
                return managed.process.returncode == 0
            except Exception as exc:
                self._remember_failure(str(exc))
                return {"ok": False, "background": True, "message": str(exc)} if background else False
        if enable_bridge is True:
            message = "A verified session-owned runtime bridge is currently supported only for macOS launches."
            self._remember_failure(message)
            return (
                {"ok": False, "background": True, "bridge_enabled": False, "message": message} if background else False
            )
        attempt_limit = self._infrastructure_attempt_limit()
        self.infrastructure_attempt_count = 0
        self.retried_infrastructure_failure = False
        for attempt in range(1, attempt_limit + 1):
            self.infrastructure_attempt_count = attempt
            if output_location == "temp":
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
        if platform_target == "macOS":
            return self.run_project_direct(platform_target, runtime_type, background, "temp")
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
            elif platform_target == "Windows":
                extra_args.append(f"--tf={ide_temp_dir / (project_name + '.zip')}")

            cmd = self._build_platform_action_command(
                "PackageZip",
                platform_target,
                runtime_type,
                extra_args=extra_args,
            )

            print(f"[CMD] Package command: {' '.join(cmd)}")

            previous_executables = (
                {
                    path: (path.stat().st_mtime_ns, path.stat().st_size)
                    for path in ide_temp_dir.glob("*.exe")
                    if path.is_file()
                }
                if platform_target == "Windows"
                else {}
            )

            # Run packaging
            self._wait_for_igor_idle()
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
                if platform_target == "Windows" and not (
                    self._compile_stage_succeeded(output_lines)
                    and any("WindowsBuilder.PackageZip" in line for line in output_lines)
                    and any("System.IO.File.Move" in line for line in output_lines)
                ):
                    self._remember_failure(
                        f"{failure_message} Build did not complete safely; refusing to launch an old build."
                    )
                    print(f"[ERROR] {self.last_failure_message}")
                    return False
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
            if platform_target == "Windows" and process.returncode != 0:
                launch_path = self._find_launch_target(
                    ide_temp_dir, project_name, platform_target, previous_executables=previous_executables
                )
            else:
                launch_path = self._find_launch_target(ide_temp_dir, project_name, platform_target)

            if not launch_path:
                failure_message = (
                    "Packaging failed without creating a fresh executable; refusing to launch an old build."
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
        """Run non-macOS targets through Igor; macOS uses the owned runtime engine."""
        platform_target = normalize_platform_target(platform_target)
        if platform_target == "macOS":
            return self.run_project_direct(platform_target, runtime_type, background, "project")
        machine_lock = GameMakerMachineLock("run-start", self.project_root)
        try:
            machine_lock.acquire()
            self._clear_last_result("local run")
            self._wait_for_igor_idle()
            cmd = self._build_platform_action_command("Run", platform_target, runtime_type)
            project_file = self.find_project_file()
            self.game_process = self._run_igor_command(cmd)
            session = self._session_manager.create_session(
                pid=self.game_process.pid,
                exe_path=str(project_file),
                platform_target=platform_target,
                runtime_type=runtime_type,
            )
            machine_lock.release()
            if background:
                return {
                    "ok": True,
                    "background": True,
                    "pid": self.game_process.pid,
                    "run_id": session.run_id,
                    "message": f"Game started in background (PID: {self.game_process.pid})",
                }
            output_lines = self._stream_igor_output(self.game_process, "local run")
            self.game_process.wait()
            self._session_manager.clear_session()
            if self.game_process.returncode == 0:
                return True
            failure_message = self._build_stage_failure_message("local run", self.game_process.returncode, output_lines)
            self._remember_failure(
                failure_message, retryable=self._is_retryable_igor_failure(self.game_process.returncode, output_lines)
            )
            return False
        except Exception as exc:
            self._remember_failure(str(exc))
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
        if session and session.isolated_runtime:
            from .. import live_session

            result = live_session.stop(self.project_root)
            self.game_process = None
            return result
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
        if (self.project_root / "gamemaker").is_dir():
            self.find_project_file()
        return self._session_manager.get_session_status()
