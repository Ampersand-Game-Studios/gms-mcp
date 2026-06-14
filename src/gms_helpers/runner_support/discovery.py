from __future__ import annotations
# pyright: reportAttributeAccessIssue=false

import os
import platform
from pathlib import Path
from typing import Optional

from ..utils import find_yyp


class RunnerDiscoveryMixin:
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
                Path("C:/Users") / os.getenv("USERNAME", "") / "AppData/Roaming/GameMakerStudio2",
            ]
        elif system == "Darwin":
            base_paths = [
                Path.home() / "Library/Application Support/GameMakerStudio2",
                Path("/Library/Application Support/GameMakerStudio2"),
                Path("/Users/Shared/GameMakerStudio2"),
            ]
        else:  # Linux
            base_paths = [Path.home() / ".config/GameMakerStudio2"]

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
