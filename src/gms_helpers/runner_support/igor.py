from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import hashlib
import os
import shutil
import subprocess
import threading
import zipfile
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

    @staticmethod
    def _igor_rejected_command(output_lines: List[str]) -> bool:
        return any("igor: unknown command" in line.lower() for line in output_lines)

    def _is_retryable_igor_failure(self, returncode: int, output_lines: List[str]) -> bool:
        output = "\n".join(output_lines)
        return (
            returncode != 0
            and "System.AccessViolationException" in output
            and not self._compile_stage_succeeded(output_lines)
        )

    @staticmethod
    def _android_package_fingerprint(path: Path) -> tuple[int, int]:
        """Return the metadata needed to distinguish this build's package from a stale one."""
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    @classmethod
    def _verified_android_packages(cls, output_root: Path) -> dict[Path, tuple[int, int]]:
        """Find structurally valid Android install/package artifacts below Igor's output root."""
        packages: dict[Path, tuple[int, int]] = {}
        for package_path in output_root.rglob("*"):
            if not package_path.is_file() or package_path.suffix.lower() not in {".apk", ".aab"}:
                continue
            try:
                if package_path.stat().st_size == 0:
                    continue
                with zipfile.ZipFile(package_path) as archive:
                    names = set(archive.namelist())
                    manifest_name = (
                        "AndroidManifest.xml"
                        if package_path.suffix.lower() == ".apk"
                        else "base/manifest/AndroidManifest.xml"
                    )
                    if archive.testzip() is None and manifest_name in names:
                        packages[package_path] = cls._android_package_fingerprint(package_path)
            except (OSError, zipfile.BadZipFile):
                continue
        return packages

    @classmethod
    def _verified_new_android_package_exists(
        cls,
        output_root: Path,
        baseline_packages: dict[Path, tuple[int, int]],
    ) -> bool:
        """Require a valid APK/AAB generated or updated by the current package invocation."""
        packages = cls._verified_android_packages(output_root)
        return any(baseline_packages.get(path) != fingerprint for path, fingerprint in packages.items())

    @classmethod
    def _verified_html5_artifacts(cls, output_root: Path) -> dict[Path, tuple[int, int]]:
        """Find structurally valid HTML5 outputs (index.html with scripts, or a zip of them)."""
        artifacts: dict[Path, tuple[int, int]] = {}
        for index_path in output_root.rglob("index.html"):
            try:
                if index_path.stat().st_size == 0:
                    continue
                scripts = [s for s in index_path.parent.rglob("*.js") if s.stat().st_size > 0]
                if not scripts:
                    continue
                artifacts[index_path] = cls._android_package_fingerprint(index_path)
                for script in scripts:
                    artifacts[script] = cls._android_package_fingerprint(script)
            except OSError:
                continue
        for archive_path in output_root.rglob("*.zip"):
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    names = [name for name in archive.namelist() if not name.endswith("/")]
                    if (
                        archive.testzip() is None
                        and any(name.endswith("index.html") for name in names)
                        and any(name.endswith(".js") for name in names)
                    ):
                        artifacts[archive_path] = cls._android_package_fingerprint(archive_path)
            except (OSError, zipfile.BadZipFile):
                continue
        return artifacts

    @classmethod
    def _verified_html5_package_exists(
        cls,
        output_root: Path,
        baseline_artifacts: dict[Path, tuple[int, int]],
    ) -> bool:
        """Require a valid HTML5 artifact generated or updated by the current package invocation."""
        artifacts = cls._verified_html5_artifacts(output_root)
        return any(baseline_artifacts.get(path) != fingerprint for path, fingerprint in artifacts.items())

    @classmethod
    def _is_verified_html5_target_type_false_failure(
        cls,
        returncode: int,
        output_lines: List[str],
        output_root: Path,
        baseline_artifacts: dict[Path, tuple[int, int]],
    ) -> bool:
        output = "\n".join(output_lines)
        return (
            returncode != 0
            and "The given key (targetType) was not present in the dictionary" in output
            and cls._compile_stage_succeeded(output_lines)
            and cls._verified_html5_package_exists(output_root, baseline_artifacts)
        )

    @staticmethod
    def _infrastructure_attempt_limit() -> int:
        raw = os.environ.get("GMS_MCP_IGOR_INFRA_ATTEMPTS", "3").strip()
        try:
            return min(3, max(1, int(raw)))
        except ValueError:
            return 3

    @staticmethod
    def _macos_compile_launch_timeout_seconds() -> float:
        """Bound the full macOS compile-and-launch wait for large projects."""
        raw = os.environ.get("GMS_MCP_MACOS_COMPILE_LAUNCH_TIMEOUT_SECONDS", "1800").strip()
        try:
            return min(7200.0, max(1.0, float(raw)))
        except ValueError:
            return 1800.0

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
        cmd.extend([f"/uf={license_file.parent}"])
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
        self,
        process: subprocess.Popen,
        stage_label: str,
        *,
        emit_output: bool = True,
        output_lines: Optional[List[str]] = None,
    ) -> List[str]:
        """Stream Igor stdout while lightly classifying lines for humans."""
        if output_lines is None:
            output_lines = []

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
        if self._igor_rejected_command(output_lines):
            return "GameMaker rejected the requested Igor command."
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
            self._stream_igor_output(
                process,
                stage_label,
                emit_output=emit_output,
                output_lines=output_lines,
            )

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        return output_lines, thread

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
                self.find_project_file()
                from .. import snapshot_build
                import shutil
                self._clear_last_result("snapshot compile")
                work = None
                try:
                    with snapshot_build.label_pipeline(self.project_root, "compile"):
                        public, build, work, _tools = snapshot_build.snapshot_compile(
                            self.project_root, label="compile", runtime=runtime_type,
                            runtime_version=self.runtime_version,
                        )
                    if not build.ok:
                        self._remember_failure(public.get("message", "Snapshot compile failed"))
                    return build.ok
                finally:
                    if work is not None:
                        shutil.rmtree(work, ignore_errors=True)

            stage_label = "package/export"
            self._clear_last_result(stage_label)
            project_file = self.find_project_file()
            system_temp = self._system_temp_root()
            project_name = project_file.stem
            ide_temp_dir = system_temp / "GameMakerStudio2" / project_name
            ide_temp_dir.mkdir(parents=True, exist_ok=True)
            android_baseline_packages = (
                self._verified_android_packages(ide_temp_dir) if platform_target == "Android" else {}
            )
            html5_baseline_artifacts = (
                self._verified_html5_artifacts(ide_temp_dir) if platform_target == "HTML5" else {}
            )

            compile_action = "Package" if platform_target in {"Android", "Linux"} else "PackageZip"
            output_args = [f"/of={ide_temp_dir / project_name}"]
            if platform_target == "Windows":
                output_args.append(f"--tf={ide_temp_dir / (project_name + '.zip')}")
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

            if process.returncode == 0 and not self._igor_rejected_command(output_lines):
                if platform_target == "Android" and not self._verified_new_android_package_exists(
                    ide_temp_dir,
                    android_baseline_packages,
                ):
                    failure_message = (
                        "Android package/export completed without producing a new verified APK or AAB artifact. "
                        "Check Android SDK/JDK and packaging settings in GameMaker, then retry."
                    )
                    self._remember_failure(failure_message)
                    print(f"[ERROR] {failure_message}")
                    return False
                print(f"[OK] {stage_label.capitalize()} completed successfully!")
                return True

            if platform_target == "HTML5" and self._is_verified_html5_target_type_false_failure(
                process.returncode,
                output_lines,
                ide_temp_dir,
                html5_baseline_artifacts,
            ):
                print(
                    "[OK] HTML5 package completed and the generated artifact was verified; "
                    "ignoring Igor's post-package targetType exception."
                )
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
