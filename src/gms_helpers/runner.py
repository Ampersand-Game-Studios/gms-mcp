#!/usr/bin/env python3
"""
GameMaker Runner Module
Provides functionality to compile and run GameMaker projects using Igor.exe
"""

import os
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
        """Locate GameMaker runtime and Igor.exe using RuntimeManager."""
        if self.igor_path:
            return self.igor_path
            
        runtime_info = self._runtime_manager.select(self.runtime_version)
        if runtime_info and runtime_info.is_valid:
            self.igor_path = Path(runtime_info.igor_path)
            self.runtime_path = Path(runtime_info.path)
            return self.igor_path
            
        return None
    
    def find_license_file(self) -> Optional[Path]:
        """Find GameMaker license file."""
        system = platform.system()
        
        if system == "Windows":
            base_paths = [
                Path.home() / "AppData/Roaming/GameMakerStudio2",
                Path("C:/Users") / os.getenv("USERNAME", "") / "AppData/Roaming/GameMakerStudio2"
            ]
        elif system == "Darwin":
            base_paths = [
                Path.home() / "Library/Application Support/GameMakerStudio2"
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
                license_file = user_dir / "licence.plist"
                if license_file.exists():
                    return license_file
        
        return None
    
    def build_igor_command(self, action: str = "Run", platform_target: str = "Windows", 
                          runtime_type: str = "VM", **kwargs) -> List[str]:
        """Build Igor.exe command line."""
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
        
        # Add runtime type
        if runtime_type.upper() == "YYC":
            cmd.extend(["/runtime=YYC"])
        
        # Add platform and action
        cmd.extend(["--", platform_target, action])
        
        return cmd
    
    def compile_project(self, platform_target: str = "Windows", runtime_type: str = "VM") -> bool:
        """Compile the GameMaker project."""
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
            
            # Output location
            cmd.extend([f"--of={ide_temp_dir / project_name}"])
            
            if runtime_type.upper() == "YYC":
                cmd.extend(["/runtime=YYC"])
            
            cmd.extend(["--", platform_target, "PackageZip"])
            
            print(f"[CMD] Command: {' '.join(cmd)}")
            
            # Run compilation
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Stream output in real-time
            if process.stdout:
                for line in process.stdout:
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
            
            process.wait()
            
            if process.returncode == 0:
                print("[OK] Compilation successful!")
                return True
            else:
                print(f"[ERROR] Compilation failed with exit code {process.returncode}")
                return False
                
        except Exception as e:
            print(f"[ERROR] Compilation error: {e}")
            return False
    
    def run_project_direct(self, platform_target="Windows", runtime_type="VM", background=False, output_location="temp"):
        """
        Run the project directly.
        
        Args:
            platform_target: Target platform (default: Windows)
            runtime_type: Runtime type VM or YYC (default: VM)
            background: Run in background (default: False)
            output_location: Where to output files - 'temp' (IDE-style, AppData) or 'project' (classic output folder)
        """
        if output_location == "temp":
            return self._run_project_ide_temp_approach(platform_target, runtime_type, background)
        else:  # output_location == "project"
            return self._run_project_classic_approach(platform_target, runtime_type, background)
    
    def _run_project_ide_temp_approach(self, platform_target="Windows", runtime_type="VM", background=False):
        """
        Run the project using IDE-temp approach:
        1. Package to zip in IDE temp directory
        2. Extract zip contents
        3. Run Runner.exe manually from extracted location
        """
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
            
            # Add output parameters (BEFORE the -- separator)
            cmd.extend([f"--of={ide_temp_dir / project_name}"])
            
            # Add runtime type
            if runtime_type.upper() == "YYC":
                cmd.extend(["/runtime=YYC"])
            
            # Add platform and action
            cmd.extend(["--", platform_target, "PackageZip"])
            
            print(f"[CMD] Package command: {' '.join(cmd)}")
            
            # Run packaging
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
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
            
            # Step 2: Check if the executable was created (PackageZip creates files directly, not a zip)
            exe_name = f"{project_name}.exe"
            exe_path = ide_temp_dir / exe_name
            
            # Check for common executable names
            possible_exes = [
                ide_temp_dir / f"{project_name}.exe",
                ide_temp_dir / "template.exe",  # Default name GameMaker uses
                ide_temp_dir / "runner.exe"
            ]
            
            exe_path = None
            for possible_exe in possible_exes:
                if possible_exe.exists():
                    exe_path = possible_exe
                    break
                    
            if not exe_path:
                print(f"[ERROR] Executable not found in: {ide_temp_dir}")
                print("Available files:")
                for file in ide_temp_dir.iterdir():
                    print(f"  - {file.name}")
                return False
                
            print(f"[OK] Game packaged successfully: {exe_path}")
            
            # Step 3: Run the executable directly
            print("[RUN] Starting game...")
            
            # Change to the game directory and run the executable
            original_cwd = os.getcwd()
            try:
                os.chdir(ide_temp_dir)
                
                # Run the game executable directly
                self.game_process = subprocess.Popen([str(exe_path)])
                
                print(f"[OK] Game started! PID: {self.game_process.pid}")
                print("   Game is running in the background...")
                print("   Close the game window to return to console.")
                
                # Wait for game to finish
                self.game_process.wait()
                
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
            
            # Add runtime type
            if runtime_type.upper() == "YYC":
                cmd.extend(["/runtime=YYC"])
            
            # Add platform and action (classic Run command)
            cmd.extend(["--", platform_target, "Run"])
            
            print(f"[CMD] Run command: {' '.join(cmd)}")
            
            # Run the game using Igor Run command
            self.game_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Stream output in real-time
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
            
            if self.game_process.returncode == 0:
                print("[OK] Game finished successfully!")
                return True
            else:
                print(f"[ERROR] Game failed with exit code {self.game_process.returncode}")
                return False
                 
        except Exception as e:
            print(f"[ERROR] Error running project: {e}")
            return False
    
    def stop_game(self) -> bool:
        """Stop the running game."""
        if not self.game_process:
            print("[WARN] No game process running")
            return False
            
        try:
            pid = self.game_process.pid
            print(f"[STOP] Stopping game (PID: {pid})...")
            
            # Terminate our subprocess
            if self.game_process.poll() is None:
                self.game_process.terminate()
                try:
                    self.game_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    print("[WARN] Process didn't terminate gracefully, forcing kill...")
                    self.game_process.kill()
            
            self.game_process = None
            print("[OK] Game stopped")
            return True
            
        except Exception as e:
            print(f"[ERROR] Error stopping game: {e}")
            return False
    
    def is_game_running(self) -> bool:
        """Check if game is currently running."""
        if not self.game_process:
            return False
        return self.game_process.poll() is None


# Convenience functions for command-line usage
def compile_project(project_root: str = ".", platform: str = "Windows", 
                   runtime: str = "VM", runtime_version: Optional[str] = None) -> bool:
    """Compile GameMaker project."""
    runner = GameMakerRunner(Path(project_root), runtime_version=runtime_version)
    return runner.compile_project(platform, runtime)


def run_project(project_root: str = ".", platform: str = "Windows", 
               runtime: str = "VM", background: bool = False, output_location: str = "temp",
               runtime_version: Optional[str] = None) -> bool:
    """Run GameMaker project directly (like IDE does)."""
    runner = GameMakerRunner(Path(project_root), runtime_version=runtime_version)
    return runner.run_project_direct(platform, runtime, background, output_location)


def stop_project(project_root: str = ".") -> bool:
    """Stop running GameMaker project."""
    runner = GameMakerRunner(Path(project_root))
    return runner.stop_game() 
