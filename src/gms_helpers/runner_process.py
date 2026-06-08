"""Process launch helpers for GameMaker runner operations."""

from __future__ import annotations

import errno
import platform
import subprocess
from pathlib import Path
from typing import List


def normalize_path_for_popen() -> dict:
    """Return platform-safe keyword args for launching subprocesses."""
    process_kwargs = {}
    if platform.system() != "Windows":
        process_kwargs["start_new_session"] = True
    return process_kwargs


def build_macos_launch_guidance(launch_target: Path, error: OSError, action: str) -> str:
    """Build a remediation message for macOS launch/runtime permission issues."""
    errno_value = getattr(error, "errno", None)
    error_text = str(error).lower()
    action_name = {
        "game": "Game launch",
        "runtime": "Runtime execution",
    }.get(action, "Subprocess")

    guidance = [
        "- Verify execute permission is set on the file (`chmod +x`).",
        '- If the file was downloaded, clear quarantine metadata (`xattr -dr com.apple.quarantine "<path>"`).',
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
        return f"{action_name} was blocked by macOS sandbox rules.\nPath: {launch_target}\nRemediation:\n{remediation}"

    if "code signature" in error_text or "codesign" in error_text:
        return (
            f"{action_name} was blocked by macOS code signing enforcement.\n"
            f"Path: {launch_target}\n"
            f"Remediation:\n{remediation}"
        )

    return f"{action_name} failed for macOS with: {error}"


def start_game_process(launch_path: Path) -> subprocess.Popen:
    """Start a game process without inheriting the caller's stdio handles."""
    try:
        process_kwargs = normalize_path_for_popen()
        process_kwargs.update(
            {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
        )
        return subprocess.Popen(
            [str(launch_path)],
            **process_kwargs,
        )
    except OSError as exc:
        if platform.system() == "Darwin":
            raise RuntimeError(build_macos_launch_guidance(launch_path, exc, "game")) from exc
        raise


def run_igor_command(cmd: List[str]) -> subprocess.Popen:
    """Start an Igor command with shared process settings."""
    process_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "universal_newlines": True,
    }
    process_kwargs.update(normalize_path_for_popen())
    try:
        return subprocess.Popen(cmd, **process_kwargs)
    except OSError as exc:
        if platform.system() == "Darwin":
            igor_path = Path(cmd[0]) if cmd else Path("<unknown>")
            raise RuntimeError(build_macos_launch_guidance(igor_path, exc, "runtime")) from exc
        raise
