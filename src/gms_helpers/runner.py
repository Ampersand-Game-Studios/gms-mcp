#!/usr/bin/env python3
"""Public runner facade for GameMaker Igor compile/run helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .run_session import RunSessionManager
from .runtime_manager import RuntimeManager
from .runner_support.artifacts import RunnerArtifactMixin
from .runner_support.discovery import RunnerDiscoveryMixin
from .runner_support.execution import RunnerExecutionMixin
from .runner_support.igor import RunnerIgorMixin
from .runner_support.macos import RunnerMacOSMixin
from .runner_support.targets import (
    GMRT_CLI_UNSUPPORTED_MESSAGE,
    _to_igor_platform,
    detect_default_target_platform,
    ensure_igor_supported_runtime_type,
    normalize_platform_target,
    normalize_runtime_type,
)


class GameMakerRunner(
    RunnerExecutionMixin,
    RunnerIgorMixin,
    RunnerMacOSMixin,
    RunnerArtifactMixin,
    RunnerDiscoveryMixin,
):
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


# Convenience functions for command-line usage
def compile_project(
    project_root: str = ".", platform: Optional[str] = None, runtime: str = "VM", runtime_version: Optional[str] = None
) -> bool:
    """Compile GameMaker project."""
    runner = GameMakerRunner(Path(project_root), runtime_version=runtime_version)
    return runner.compile_project(platform, runtime)


def run_project(
    project_root: str = ".",
    platform: Optional[str] = None,
    runtime: str = "VM",
    background: bool = False,
    output_location: str = "temp",
    runtime_version: Optional[str] = None,
):
    """
    Run GameMaker project directly (like IDE does).

    Args:
        project_root: Path to project root
        platform: Target platform (default: host OS)
        runtime: Runtime type VM or YYC (default: VM); GMS2 VM/YYC aliases are accepted
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
