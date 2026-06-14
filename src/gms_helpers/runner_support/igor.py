from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

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

    def _remember_failure(self, message: str) -> None:
        """Store the most recent runner failure for command wrappers."""
        self.last_failure_message = message

    def _system_temp_root(self) -> Path:
        """Return the system temp directory used for Igor cache/temp folders."""
        import tempfile

        return Path(tempfile.gettempdir())

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
        """Compile the GameMaker project."""
        platform_target = normalize_platform_target(platform_target)

        try:
            runtime_type = ensure_igor_supported_runtime_type(runtime_type)
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
