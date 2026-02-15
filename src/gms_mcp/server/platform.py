from __future__ import annotations

import platform


def _default_target_platform() -> str:
    """Choose the GameMaker target platform that matches the host OS."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Linux":
        return "Linux"
    return "Windows"

