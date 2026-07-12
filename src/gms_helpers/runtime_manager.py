"""
GameMaker Runtime Management
Discovery, selection, and pinning of runtime versions.
"""

import os
import platform
import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class RuntimeInfo:
    """Detailed information about an installed GameMaker runtime."""

    version: str  # e.g., "2024.1100.0.625"
    path: str  # Path to runtime directory
    igor_path: str  # Path to Igor executable
    is_valid: bool  # Whether Igor exists
    release_channel: str  # "stable" | "beta" | "lts" | "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_runtime_channel(version: str) -> str:
    """Classify a GameMaker runtime version into a release channel."""
    normalized = (version or "").strip().lower()
    if normalized.startswith("runtime-"):
        normalized = normalized.removeprefix("runtime-")

    if not normalized:
        return "unknown"

    if normalized.startswith(("2.", "2022.", "2026.")):
        return "lts"

    parts = normalized.split(".")
    if len(parts) > 1 and parts[1].isdigit() and int(parts[1]) >= 1000:
        return "beta"

    return "stable"


def _runtime_sort_key(version: str) -> tuple[int, ...]:
    """Sort dotted runtime versions numerically instead of lexicographically."""
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _runtime_roots(parent: Path) -> List[Path]:
    if not parent.exists():
        return []
    return sorted(path for path in parent.glob("GameMakerStudio2*/Cache/runtimes") if path.is_dir())


class RuntimeManager:
    """Manages GameMaker runtime discovery, selection, and pinning."""

    CONFIG_DIR = ".gms_mcp"
    CONFIG_FILE = "runtime.json"
    ENV_VAR = "GMS_RUNTIME_VERSION"

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._cached_runtimes: Optional[List[RuntimeInfo]] = None

    def list_installed(self) -> List[RuntimeInfo]:
        """Discover all installed runtimes on the system."""
        if self._cached_runtimes is not None:
            return self._cached_runtimes

        system = platform.system()
        possible_paths = []

        if system == "Windows":
            program_data = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
            app_data = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
            possible_paths = [*_runtime_roots(program_data), *_runtime_roots(app_data)]
        elif system == "Darwin":  # macOS
            possible_paths = [
                *_runtime_roots(Path("/Users/Shared")),
                *_runtime_roots(Path.home() / "Library/Application Support"),
            ]
        else:  # Linux
            possible_paths = [
                *_runtime_roots(Path.home() / ".local/share"),
                *_runtime_roots(Path("/var/opt")),
                *_runtime_roots(Path("/opt")),
            ]

        possible_paths = list(dict.fromkeys(path.resolve() for path in possible_paths))

        runtimes = []
        for base_path in possible_paths:
            if not base_path.exists():
                continue

            for runtime_dir in base_path.glob("runtime-*"):
                if not runtime_dir.is_dir():
                    continue

                version = runtime_dir.name.replace("runtime-", "")

                # Find Igor
                igor_path = None
                if system == "Windows":
                    patterns = ["bin/igor/windows/x64/Igor.exe", "bin/igor/windows/Igor.exe"]
                elif system == "Darwin":
                    patterns = [
                        "bin/igor/osx/arm64/Igor",
                        "bin/igor/osx/x64/Igor",
                        "bin/igor/osx/Igor",
                    ]
                else:
                    patterns = ["bin/igor/linux/x64/Igor", "bin/igor/linux/Igor"]

                for p in patterns:
                    candidate = runtime_dir / p
                    if candidate.exists():
                        igor_path = candidate
                        break

                channel = classify_runtime_channel(version)

                runtimes.append(
                    RuntimeInfo(
                        version=version,
                        path=str(runtime_dir),
                        igor_path=str(igor_path) if igor_path else "",
                        is_valid=igor_path is not None,
                        release_channel=channel,
                    )
                )

        # Sort newest first
        runtimes.sort(key=lambda x: _runtime_sort_key(x.version), reverse=True)
        self._cached_runtimes = runtimes
        return runtimes

    def get_pinned(self) -> Optional[str]:
        """Get pinned runtime version for this project."""
        # 1. Check environment variable
        env_version = os.environ.get(self.ENV_VAR)
        if env_version:
            return env_version

        # 2. Check config file
        config_path = self.project_root / self.CONFIG_DIR / self.CONFIG_FILE
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)
                    return data.get("pinned_version")
            except Exception:
                pass

        return None

    def pin(self, version: str) -> bool:
        """Pin a specific runtime version for this project."""
        # Validate version exists
        installed = self.list_installed()
        if not any(r.version == version for r in installed):
            return False

        config_dir = self.project_root / self.CONFIG_DIR
        config_dir.mkdir(parents=True, exist_ok=True)

        config_path = config_dir / self.CONFIG_FILE
        data = {"pinned_version": version, "pinned_at": datetime.now().isoformat(), "pinned_by": "gms-mcp"}

        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

        return True

    def unpin(self) -> bool:
        """Remove runtime pin."""
        config_path = self.project_root / self.CONFIG_DIR / self.CONFIG_FILE
        if config_path.exists():
            config_path.unlink()
            return True
        return False

    def select(self, version_override: Optional[str] = None) -> Optional[RuntimeInfo]:
        """Select the best runtime to use."""
        installed = self.list_installed()
        if not installed:
            return None

        target_version = version_override or self.get_pinned()

        if target_version:
            for r in installed:
                if r.version == target_version:
                    return r
            # If pinned version not found, we could fallback, but better to return None
            # or handle it in the caller. Let's return None to signal missing specific version.
            return None

        # Default: match the project's recorded IDE family, otherwise prefer
        # the newest stable runtime over beta/LTS installations.
        valid = [r for r in installed if r.is_valid]
        preferred_channel = self._project_release_channel()
        if preferred_channel:
            matching = [runtime for runtime in valid if runtime.release_channel == preferred_channel]
            if matching:
                return matching[0]
        stable = [runtime for runtime in valid if runtime.release_channel == "stable"]
        return stable[0] if stable else (valid[0] if valid else installed[0])

    def _project_release_channel(self) -> Optional[str]:
        """Infer the intended runtime family from the project's recorded IDE version."""
        try:
            yyp_files = sorted(self.project_root.glob("*.yyp"))
            if len(yyp_files) != 1:
                return None
            text = yyp_files[0].read_text(encoding="utf-8", errors="ignore")
            match = re.search(r'"IDEVersion"\s*:\s*"([^"]+)"', text)
            if not match:
                return None
            channel = classify_runtime_channel(match.group(1))
            return channel if channel in {"stable", "beta", "lts"} else None
        except OSError:
            return None

    def verify(self, version: Optional[str] = None) -> Dict[str, Any]:
        """Verify a runtime is valid and ready to use."""
        runtime = self.select(version)
        if not runtime:
            return {"ok": False, "issues": ["No matching runtime found."]}

        issues = []
        if not runtime.is_valid:
            issues.append(f"Igor executable missing in runtime {runtime.version}")

        # Check license
        from .runner import GameMakerRunner

        runner = GameMakerRunner(self.project_root)
        license_file = runner.find_license_file()
        if not license_file:
            issues.append("GameMaker license file not found. Please log into the IDE.")

        return {
            "ok": len(issues) == 0,
            "version": runtime.version,
            "checks": {
                "runtime_exists": True,
                "igor_executable": runtime.is_valid,
                "license_found": license_file is not None,
            },
            "issues": issues,
        }
