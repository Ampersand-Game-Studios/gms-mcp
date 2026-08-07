from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import hashlib
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import List, Optional

from ..exceptions import LicenseNotFoundError, RuntimeNotFoundError
from .targets import _to_igor_platform, ensure_igor_supported_runtime_type, normalize_platform_target


class RunnerIgorMixin:
    def _clear_last_result(self, action_label: str) -> None:
        """Reset the remembered result state for a new runner action."""
        self.last_action_label = action_label
        self.last_failure_message = None
        self.last_failure_retryable = False

    def _remember_failure(self, message: str, *, retryable: bool = False) -> None:
        """Store the most recent runner failure for command wrappers."""
        self.last_failure_message = message
        self.last_failure_retryable = retryable

    @staticmethod
    def _compile_stage_succeeded(output_lines: List[str]) -> bool:
        output = "\n".join(output_lines)
        compile_finished = "Final Compile finished" in output and "Saving IFF file" in output
        return compile_finished and ("Igor complete." in output or "Stats : GMA" in output)

    def _is_retryable_igor_failure(self, returncode: int, output_lines: List[str]) -> bool:
        output = "\n".join(output_lines)
        return (
            returncode != 0
            and "System.AccessViolationException" in output
            and not self._compile_stage_succeeded(output_lines)
        )

    @staticmethod
    def _infrastructure_attempt_limit() -> int:
        raw = os.environ.get("GMS_MCP_IGOR_INFRA_ATTEMPTS", "3").strip()
        try:
            return min(3, max(1, int(raw)))
        except ValueError:
            return 3

    def _system_temp_root(self) -> Path:
        """Return the system temp directory used for Igor cache/temp folders."""
        import tempfile

        return Path(tempfile.gettempdir())

    def _igor_work_root(self) -> Path:
        """Return the project/runtime-scoped disposable Igor work directory."""
        if not self.runtime_path:
            raise RuntimeNotFoundError("GameMaker runtime path is not initialized.")
        project_file = self.find_project_file()
        runtime_scope = str(Path(self.runtime_path).resolve())
        project_scope = str(project_file.resolve())
        work_key = hashlib.sha256(f"{project_scope}\0{runtime_scope}".encode("utf-8")).hexdigest()[:16]
        return self._system_temp_root() / "gms-mcp" / work_key

    def _reset_igor_transient_state(self) -> None:
        """Discard one project's disposable cache before an infrastructure retry."""
        work_root = self._igor_work_root()
        expected_parent = (self._system_temp_root() / "gms-mcp").resolve()
        if work_root.parent.resolve() != expected_parent:
            raise RuntimeError(f"Refusing to clear unexpected Igor work path: {work_root}")
        if work_root.exists():
            shutil.rmtree(work_root)

    def _append_runtime_type_arg(self, cmd: List[str], runtime_type: str) -> None:
        """Append the Igor runtime switch when requested."""
        runtime_type = ensure_igor_supported_runtime_type(runtime_type)
        if runtime_type == "YYC":
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

        work_root = self._igor_work_root()
        cache_dir = work_root / "cache"
        temp_dir = work_root / "temp"
        cache_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

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

    def _stream_igor_output(
        self, process: subprocess.Popen, stage_label: str, *, emit_output: bool = True
    ) -> List[str]:
        """Stream Igor stdout while lightly classifying lines for humans."""
        output_lines: List[str] = []

        if not process.stdout:
            return output_lines

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            output_lines.append(line)
            if not emit_output:
                continue
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
        if self._is_retryable_igor_failure(returncode, output_lines):
            return "GameMaker runtime aborted with System.AccessViolationException before compilation completed."
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

    def _collect_igor_output_async(
        self,
        process: subprocess.Popen,
        stage_label: str,
        *,
        emit_output: bool = True,
    ) -> tuple[List[str], threading.Thread]:
        """Stream Igor output in a background thread while the caller polls side effects."""
        output_lines: List[str] = []

        def _reader() -> None:
            output_lines.extend(self._stream_igor_output(process, stage_label, emit_output=emit_output))

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        return output_lines, thread

    def _build_macos_compile_validation_command(self, runtime_type: str) -> List[str]:
        """
        Build the macOS compile-validation command.

        Igor exposes local `Run` and packaging/export actions on macOS, but not a pure
        compile-only local build mode. For local validation we use `Run`, wait until the
        runner reaches the game main loop, then issue `Stop`.
        """
        return self._build_platform_action_command("Run", "macOS", runtime_type)

    def build_igor_command(
        self, action: str = "Run", platform_target: Optional[str] = None, runtime_type: str = "VM", **kwargs
    ) -> List[str]:
        """Build Igor command line."""
        return self._build_platform_action_command(action, platform_target, runtime_type)

    def compile_project(self, platform_target: Optional[str] = None, runtime_type: str = "VM") -> bool:
        """Compile the project, retrying only a confirmed pre-compile Igor infrastructure abort."""
        attempt_limit = self._infrastructure_attempt_limit()
        self.infrastructure_attempt_count = 0
        self.retried_infrastructure_failure = False
        for attempt in range(1, attempt_limit + 1):
            self.infrastructure_attempt_count = attempt
            success = self._compile_project_once(platform_target, runtime_type)
            if success or self.last_failure_retryable is not True or attempt >= attempt_limit:
                return success
            self.retried_infrastructure_failure = True
            try:
                self._reset_igor_transient_state()
            except OSError as exc:
                message = f"Could not clear GameMaker transient state before retry: {exc}"
                self._remember_failure(message)
                print(f"[ERROR] {message}")
                return False
            print(
                f"[RETRY] GameMaker runtime infrastructure abort on attempt {attempt}/{attempt_limit}; "
                "cleared transient state and retrying."
            )
        return False

    def _compile_project_once(self, platform_target: Optional[str] = None, runtime_type: str = "VM") -> bool:
        """Run one compile attempt."""
        platform_target = normalize_platform_target(platform_target)

        try:
            runtime_type = ensure_igor_supported_runtime_type(runtime_type)
            print(f"[BUILD] Compiling project for {platform_target} ({runtime_type})...")

            if platform_target == "macOS":
                self._clear_last_result("local compile validation")
                self._wait_for_igor_idle()
                cmd = self._build_macos_compile_validation_command(runtime_type)
                print("[BUILD] Using bounded Igor local run validation on macOS to avoid package signing.")
                print(f"[CMD] Validation command: {' '.join(cmd)}")
                project_name = self.find_project_file().stem
                debug_log = self._macos_debug_log_path()
                game_path = self.project_root / "output" / project_name / "game.ios"
                self._wait_for_igor_idle(timeout_seconds=0)
                baseline_processes = self._snapshot_macos_processes()
                baseline_runner_pids = {
                    pid: process for pid, process in baseline_processes.items() if "/Mac_Runner" in process.command
                }
                baseline_tail_pids = {
                    pid: process for pid, process in baseline_processes.items() if "tail -F" in process.command
                }
                macos_launch_token = self._new_macos_launch_token()
                self._write_macos_ownership_manifest(
                    baseline_processes,
                    game_path,
                    debug_log,
                    macos_launch_token,
                )
                if not baseline_runner_pids and not baseline_tail_pids:
                    # GameMaker may truncate and then quickly regrow the same log
                    # beyond its prior size. Starting from a clean transient log
                    # prevents a stale byte offset from missing the new main-loop marker.
                    try:
                        debug_log.unlink(missing_ok=True)
                    except OSError:
                        pass
                start_offset = debug_log.stat().st_size if debug_log.exists() else 0
                output_lines: List[str] = []
                output_thread: Optional[threading.Thread] = None
                process = None
                owned_igor_command: Optional[str] = None
                owned_igor_started: Optional[str] = None
                reached_main_loop = False
                timed_out = False
                try:
                    process = self._run_igor_command(
                        cmd,
                        environment_overrides={self._MACOS_LAUNCH_TOKEN_ENV: macos_launch_token},
                    )
                    launched_processes = self._snapshot_macos_processes()
                    if process.pid in launched_processes:
                        owned_igor_command = launched_processes[process.pid].command
                        owned_igor_started = launched_processes[process.pid].started
                    self._reject_foreign_igor_after_launch(process.pid)
                    output_lines, output_thread = self._collect_igor_output_async(process, "local compile validation")
                    runner_pid, _runner_pids, _tail_pids = self._wait_for_macos_runner_start(
                        process,
                        game_path,
                        debug_log,
                        baseline_runner_pids,
                        baseline_tail_pids,
                        macos_launch_token,
                        timeout_seconds=90.0,
                    )
                    if runner_pid is not None:
                        runner_process = self._snapshot_macos_processes().get(runner_pid)
                        if runner_process is not None:
                            game_path = self._macos_runner_game_path(runner_process.command) or game_path
                            debug_log = self._macos_runner_debug_path(runner_process.command) or (
                                game_path.parent / "debug.log"
                            )
                            start_offset = 0
                        reached_main_loop = self._wait_for_macos_main_loop(
                            process, debug_log, start_offset, timeout_seconds=90.0
                        )
                    timed_out = (not reached_main_loop) and process.poll() is None
                finally:
                    if process is not None and process.poll() is None:
                        print("[BUILD] Stopping macOS local validation run...")
                        stop_ok = self._stop_platform_process("macOS", runtime_type)
                        if not stop_ok:
                            print(
                                "[WARN] Igor Stop command did not report success; terminating validation process directly."
                            )
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
                        process.pid if process is not None else None,
                        owned_igor_command,
                        owned_igor_started,
                        macos_launch_token,
                        sweep_seconds=3.0,
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
                retryable = self._is_retryable_igor_failure(
                    process.returncode if process is not None else -1,
                    output_lines,
                )
                self._remember_failure(failure_message, retryable=retryable)
                print(f"[ERROR] {failure_message}")
                return False

            stage_label = "package/export"
            self._clear_last_result(stage_label)
            project_file = self.find_project_file()
            system_temp = self._system_temp_root()
            project_name = project_file.stem
            ide_temp_dir = system_temp / "GameMakerStudio2" / project_name
            ide_temp_dir.mkdir(parents=True, exist_ok=True)

            compile_action = "Package" if platform_target == "Linux" else "PackageZip"
            output_args = [f"/of={ide_temp_dir / project_name}"]
            cmd = self._build_platform_action_command(
                compile_action,
                platform_target,
                runtime_type,
                extra_args=output_args,
            )
            print(f"[CMD] {stage_label.capitalize()} command: {' '.join(cmd)}")

            self._wait_for_igor_idle()
            process = self._run_igor_command(cmd)
            output_lines = self._stream_igor_output(process, stage_label)
            process.wait()

            if process.returncode == 0:
                print(f"[OK] {stage_label.capitalize()} completed successfully!")
                return True

            failure_message = self._build_stage_failure_message(stage_label, process.returncode, output_lines)
            self._remember_failure(
                failure_message,
                retryable=self._is_retryable_igor_failure(process.returncode, output_lines),
            )
            print(f"[ERROR] {failure_message}")
            return False

        except Exception as e:
            self._remember_failure(str(e))
            print(f"[ERROR] Compilation error: {e}")
            return False
