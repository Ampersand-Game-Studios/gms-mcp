from __future__ import annotations

import platform
from typing import Optional

from ..exceptions import RuntimeNotFoundError


GMRT_CLI_UNSUPPORTED_MESSAGE = (
    "GMRT command-line builds are not supported by gms-mcp yet. "
    "The current GameMaker LTS command-line manual documents Igor /runtime=VM|YYC only; "
    "use the GameMaker IDE for GMRT targets until YoYo publishes the Igor CLI syntax."
)


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


def normalize_runtime_type(runtime_type: Optional[str]) -> str:
    """Normalize GameMaker runtime labels from old and LTS2026 UI naming."""
    raw = (runtime_type or "VM").strip()
    key = " ".join(raw.replace("_", " ").replace("-", " ").upper().split())
    compact = key.replace(" ", "")

    aliases = {
        "VM": "VM",
        "GMS2VM": "VM",
        "YYC": "YYC",
        "GMS2YYC": "YYC",
        "GMRT": "GMRT",
        "NATIVEGMRT": "GMRT",
        "GMRTNATIVE": "GMRT",
        "GMRTVM": "GMRT VM",
    }
    normalized = aliases.get(compact)
    if normalized:
        return normalized

    valid = "VM, YYC, GMS2 VM, GMS2 YYC, GMRT, or GMRT VM"
    raise ValueError(f"Unsupported runtime type '{runtime_type}'. Expected one of: {valid}.")


def ensure_igor_supported_runtime_type(runtime_type: Optional[str]) -> str:
    """Return an Igor-supported runtime type or raise for known unsupported GMRT labels."""
    normalized = normalize_runtime_type(runtime_type)
    if normalized.startswith("GMRT"):
        raise RuntimeNotFoundError(GMRT_CLI_UNSUPPORTED_MESSAGE)
    return normalized
