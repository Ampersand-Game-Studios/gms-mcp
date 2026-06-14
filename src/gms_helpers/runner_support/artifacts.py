from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional

from ..runner_process import (
    build_macos_launch_guidance,
    normalize_path_for_popen,
    run_igor_command,
    start_game_process,
)
from .targets import normalize_platform_target


class RunnerArtifactMixin:
    def _normalize_path_for_popen(self) -> dict:
        """Return platform-safe keyword args for launching subprocesses."""
        return normalize_path_for_popen()

    def _build_macos_launch_guidance(self, launch_target: Path, error: OSError, action: str) -> str:
        """Build a remediation message for macOS launch/runtime permission issues."""
        return build_macos_launch_guidance(launch_target, error, action)

    def _start_game_process(self, launch_path: Path) -> subprocess.Popen:
        """Start a game process without inheriting the caller's stdio handles."""
        return start_game_process(launch_path)

    def _run_igor_command(self, cmd: List[str]) -> subprocess.Popen:
        """Start an Igor command with shared process settings."""
        return run_igor_command(cmd)

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
