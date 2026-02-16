#!/usr/bin/env python3
"""
GameMaker Runner Module
Provides functionality to compile and run GameMaker projects using Igor
"""

import os
import errno
import sys
import subprocess
import signal
import platform
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

    def build_igor_command(self, action: str = "Run", platform_target: Optional[str] = None,
                          runtime_type: str = "VM", **kwargs) -> List[str]:
        """Build Igor command line."""
        platform_target = normalize_platform_target(platform_target)
        igor_platform = _to_igor_platform(platform_target)

        igor_path = self.find_gamemaker_runtime()
        if not igor_path:
            raise RuntimeNotFoundError("GameMaker runtime not found. Please install GameMaker Studio.")
            
        project_file = self.find_project_file()
        license_file = self.find_license_file()
        
        if not license_file:
            raise LicenseNotFoundError("GameMaker license file not found. Please log into GameMaker IDE first.")
        
        # Build command
        cmd = [str(igor_path)]
        
        # Add license file
        cmd.extend([f"/lf={license_file}"])
        
        # Add runtime path
        cmd.extend([f"/rp={self.runtime_path}"])
        
        # Add project file
        cmd.extend([f"/project={project_file}"])
        
        # Add cache directory (use system temp like IDE does)
        import tempfile
        system_temp = Path(tempfile.gettempdir())
        cache_dir = system_temp / "gms_cache"
        cmd.extend([f"/cache={cache_dir}"])
        
        # Add temp directory (use system temp like IDE does)
        temp_dir = system_temp / "gms_temp"
        cmd.extend([f"/temp={temp_dir}"])
        

        # Add prefabs path if available (required for projects with ForcedPrefabProjectReferences)
        prefabs_path = self.get_prefabs_path()
        if prefabs_path:
            cmd.extend([f"--pf={prefabs_path}"])

        # Add runtime type
        if runtime_type.upper() == "YYC":
            cmd.extend(["/runtime=YYC"])
        
        # Add platform and action
        cmd.extend(["--", igor_platform, action])
        
        return cmd
    
    def compile_project(self, platform_target: Optional[str] = None, runtime_type: str = "VM") -> bool:
        """Compile the GameMaker project."""
        platform_target = normalize_platform_target(platform_target)
        igor_platform = _to_igor_platform(platform_target)

        try:
            print(f"[BUILD] Compiling project for {platform_target} ({runtime_type})...")

            # Use Igor PackageZip (same as the IDE run pipeline) but do not launch the executable.
            # This ensures we get a valid build in the temp area without actually starting the game.
            
            project_file = self.find_project_file()
            import tempfile
            system_temp = Path(tempfile.gettempdir())
            project_name = project_file.stem
            
            # Use IDE temp directory structure
            ide_temp_dir = system_temp / "GameMakerStudio2" / project_name
            ide_temp_dir.mkdir(parents=True, exist_ok=True)
            
            igor_path = self.find_gamemaker_runtime()
            if not igor_path or not self.runtime_path:
                raise RuntimeNotFoundError("GameMaker runtime not found")
            
            license_file = self.find_license_file()
            if not license_file:
                raise LicenseNotFoundError("GameMaker license file not found")
            
            # Build Igor command for PackageZip
            cmd = [str(igor_path)]
            cmd.extend([f"/lf={license_file}"])
            cmd.extend([f"/rp={self.runtime_path}"])
            cmd.extend([f"/project={project_file}"])
            
            cache_dir = system_temp / "gms_cache"
            temp_dir = system_temp / "gms_temp"
            cmd.extend([f"/cache={cache_dir}"])
            cmd.extend([f"/temp={temp_dir}"])
            
            # Add prefabs path if available (required for projects with ForcedPrefabProjectReferences)
            prefabs_path = self.get_prefabs_path()
            if prefabs_path:
                cmd.extend([f"--pf={prefabs_path}"])

            # Output location
            cmd.extend([f"--of={ide_temp_dir / project_name}"])

            # macOS PackageZip needs an explicit target filename for the zipped .app output.
            if platform_target == "macOS":
                cmd.extend([f"--tf={ide_temp_dir / f'{project_name}.app.zip'}"])
            
            if runtime_type.upper() == "YYC":
                cmd.extend(["/runtime=YYC"])
            
            cmd.extend(["--", igor_platform, "PackageZip"])
            
            print(f"[CMD] Command: {' '.join(cmd)}")
            
            # Run compilation
            process = self._run_igor_command(cmd)
            output_lines = []
            
            # Stream output in real-time
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        output_lines.append(line)
                        # Basic log filtering
                        if "error" in line.lower():
                            print(f"[ERROR] {line}")
                        elif "warning" in line.lower():
                            print(f"[WARN] {line}")
                        elif "compile" in line.lower() or "build" in line.lower():
                            print(f"[BUILD] {line}")
                        else:
                            print(f"   {line}")
            
            process.wait()
            
            if process.returncode == 0:
                print("[OK] Compilation successful!")
                return True
            else:
                if platform_target == "macOS":
                    signed_artifact_exists = (
                        (ide_temp_dir / f"{project_name}.app.zip").exists()
                        or (ide_temp_dir / f"{project_name}.app").exists()
                    )
                    signing_failure_markers = (
                        "SecKeychainUnlock",
                        "CreateMacExecutable",
                        "Unable to obtain authorization for this operation",
                    )
                    saw_signing_failure = any(
                        any(marker in line for marker in signing_failure_markers)
                        for line in output_lines
                    )
                    if signed_artifact_exists and saw_signing_failure:
                        print(
                            "[WARN] Igor reported a macOS signing/keychain error after producing build artifacts. "
                            "Treating compile as successful for local development."
                        )
                        return True
                print(f"[ERROR] Compilation failed with exit code {process.returncode}")
                return False
                
        except Exception as e:
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
        igor_platform = _to_igor_platform(platform_target)

        try:
            import tempfile
            import os
            import subprocess
            import platform
            from pathlib import Path
            
            print("[RUN] Starting game using IDE-temp approach...")
            
            # Step 1: Build PackageZip command to compile to IDE temp directory
            print("[PACKAGE] Packaging project to IDE temp directory...")
            
            project_file = self.find_project_file()
            system_temp = Path(tempfile.gettempdir())
            project_name = project_file.stem
            
            # Use IDE temp directory structure
            ide_temp_dir = system_temp / "GameMakerStudio2" / project_name
            ide_temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Find required files
            igor_path = self.find_gamemaker_runtime()
            if not igor_path or not self.runtime_path:
                raise RuntimeNotFoundError("GameMaker runtime not found")
            
            license_file = self.find_license_file()
            if not license_file:
                raise LicenseNotFoundError("GameMaker license file not found")
            
            # Build Igor command manually with correct parameter order
            cmd = [str(igor_path)]
            
            # Add license file
            cmd.extend([f"/lf={license_file}"])
            
            # Add runtime path
            cmd.extend([f"/rp={self.runtime_path}"])
            
            # Add project file
            cmd.extend([f"/project={project_file}"])
            
            # Add cache and temp directories
            cache_dir = system_temp / "gms_cache"
            temp_dir = system_temp / "gms_temp"
            cmd.extend([f"/cache={cache_dir}"])
            cmd.extend([f"/temp={temp_dir}"])
            
            # Add prefabs path if available (required for projects with ForcedPrefabProjectReferences)
            prefabs_path = self.get_prefabs_path()
            if prefabs_path:
                cmd.extend([f"--pf={prefabs_path}"])

            # Add output parameters (BEFORE the -- separator)
            cmd.extend([f"--of={ide_temp_dir / project_name}"])

            target_app_zip = None
            if platform_target == "macOS":
                target_app_zip = ide_temp_dir / f"{project_name}.app.zip"
                cmd.extend([f"--tf={target_app_zip}"])
            
            # Add runtime type
            if runtime_type.upper() == "YYC":
                cmd.extend(["/runtime=YYC"])
            
            # Add platform and action
            cmd.extend(["--", igor_platform, "PackageZip"])
            
            print(f"[CMD] Package command: {' '.join(cmd)}")
            
            # Run packaging
            process = self._run_igor_command(cmd)
            
            # Stream compilation output
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        if "error" in line.lower():
                            print(f"[ERROR] {line}")
                        elif "warning" in line.lower():
                            print(f"[WARN] {line}")
                        elif "compile" in line.lower() or "build" in line.lower():
                            print(f"[BUILD] {line}")
                        else:
                            print(f"   {line}")
            
            process.wait()
            
            # PackageZip might fail at the end when trying to create zip, but executable creation usually succeeds
            if process.returncode != 0:
                print(f"[WARN] Igor PackageZip returned exit code {process.returncode}, checking if executable was created...")
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
            print(f"[ERROR] Error running project: {e}")
            return False
    
    def _run_project_classic_approach(self, platform_target="Windows", runtime_type="VM", background=False):
        """
        Run the project using the classic approach:
        1. Use Igor Run command (creates output folder in project directory)
        2. Game runs directly from Igor
        """
        platform_target = normalize_platform_target(platform_target)
        igor_platform = _to_igor_platform(platform_target)

        try:
            import tempfile
            import os
            import subprocess
            import platform
            from pathlib import Path
            
            print("[RUN] Starting game using classic approach...")
            
            # Build Igor command for classic Run (no --of parameter, creates output folder)
            igor_path = self.find_gamemaker_runtime()
            if not igor_path or not self.runtime_path:
                raise RuntimeNotFoundError("GameMaker runtime not found")
            
            project_file = self.find_project_file()
            license_file = self.find_license_file()
            
            if not license_file:
                raise LicenseNotFoundError("GameMaker license file not found")
            
            # Build Igor command - classic approach (no --of parameter)
            cmd = [str(igor_path)]
            
            # Add license file
            cmd.extend([f"/lf={license_file}"])
            
            # Add runtime path
            cmd.extend([f"/rp={self.runtime_path}"])
            
            # Add project file
            cmd.extend([f"/project={project_file}"])
            
            # Add cache and temp directories
            import tempfile
            system_temp = Path(tempfile.gettempdir())
            cache_dir = system_temp / "gms_cache"
            temp_dir = system_temp / "gms_temp"
            cmd.extend([f"/cache={cache_dir}"])
            cmd.extend([f"/temp={temp_dir}"])

            # Add prefabs path if available (required for projects with ForcedPrefabProjectReferences)
            prefabs_path = self.get_prefabs_path()
            if prefabs_path:
                cmd.extend([f"--pf={prefabs_path}"])

            # Add runtime type
            if runtime_type.upper() == "YYC":
                cmd.extend(["/runtime=YYC"])

            # Add platform and action (classic Run command)
            cmd.extend(["--", igor_platform, "Run"])
            
            print(f"[CMD] Run command: {' '.join(cmd)}")
            
            # Run the game using Igor Run command
            self.game_process = self._run_igor_command(cmd)
            
            # Create a persistent session so stop/status can find this process later
            project_file = self.find_project_file()
            session = self._session_manager.create_session(
                pid=self.game_process.pid,
                exe_path=str(project_file),  # For classic approach, we use project file as reference
                platform_target=platform_target,
                runtime_type=runtime_type,
            )
            
            if background:
                # Background mode: return immediately without waiting
                # Note: For classic approach, Igor manages the game process
                # We can't easily capture output in background mode
                print(f"[OK] Game started in background mode (PID: {self.game_process.pid})")
                print(f"   Session ID: {session.run_id}")
                print("   Use gm_run_status to check if game is running.")
                print("   Use gm_run_stop to stop the game.")
                return {
                    "ok": True,
                    "background": True,
                    "pid": self.game_process.pid,
                    "run_id": session.run_id,
                    "message": f"Game started in background (PID: {self.game_process.pid})",
                }
            
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
            else:
                print(f"[ERROR] Game failed with exit code {self.game_process.returncode}")
                return False
                 
        except Exception as e:
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
