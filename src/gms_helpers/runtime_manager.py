"""
GameMaker Runtime Management
Discovery, selection, and pinning of runtime versions.
"""

import os
import platform
import json
import re
import stat
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
from .path_safety import assert_project_tree_contained
from .transactions import transactional_unlink
from .utils import atomic_write_text


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
    names = (
        "GameMakerStudio2",
        "GameMakerStudio2-Beta",
        "GameMakerStudio2-LTS",
        "GameMakerStudio2-LTS2022",
        "GameMakerStudio2-LTS2026",
    )
    return sorted(path for name in names if (path := parent / name / "Cache/runtimes").is_dir())


def default_runtime_roots(system: str | None = None) -> List[Path]:
    """GameMaker's own runtime caches for this platform; the IDE builds from these."""
    system = system or platform.system()
    if system == "Windows":
        program_data = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
        app_data = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
        roots = [*_runtime_roots(program_data), *_runtime_roots(app_data)]
    elif system == "Darwin":
        roots = [*_runtime_roots(Path("/Users/Shared")), *_runtime_roots(Path.home() / "Library/Application Support")]
    else:
        roots = [
            *_runtime_roots(Path.home() / ".local/share"),
            *_runtime_roots(Path("/var/opt")),
            *_runtime_roots(Path("/opt")),
        ]
    return list(dict.fromkeys(path.absolute() for path in roots))


def is_default_cache_runtime(runtime_dir: Path) -> bool:
    """Whether a runtime sits in GameMaker's default cache and no explicit root was chosen."""
    if os.environ.get(RuntimeManager.RUNTIME_ROOT_ENV_VAR) is not None:
        return False
    return Path(os.path.abspath(runtime_dir)).parent in default_runtime_roots()


def _runtime_components(runtime_dir: Path, igor_path: Path | None) -> tuple[list[Path] | None, str | None]:
    target = Path(os.path.abspath(igor_path)) if igor_path is not None else runtime_dir
    try:
        target.relative_to(runtime_dir)
        components = [target]
        while components[-1] != runtime_dir:
            components.append(components[-1].parent)
        for path in [*components, runtime_dir.parent]:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return None, "runtime component is a symlink or reparse point"
            expected_file = path == target and igor_path is not None
            if not (stat.S_ISREG(info.st_mode) if expected_file else stat.S_ISDIR(info.st_mode)):
                return None, "runtime component is not a regular file or directory"
    except (OSError, ValueError):
        return None, "runtime trust could not be verified"
    return components, None


def runtime_trust_issue(runtime_dir: Path, igor_path: Path | None) -> str | None:
    """Return why a runtime must not be used, or None.

    GameMaker's default caches are trusted as the IDE trusts them: the IDE runs Igor
    from the same shared folders, so refusing them would protect nothing. Every
    other location must also pass ownership and permission checks.
    """
    runtime_dir = Path(os.path.abspath(runtime_dir))
    components, issue = _runtime_components(runtime_dir, igor_path)
    if issue or components is None:
        return issue
    if is_default_cache_runtime(runtime_dir):
        return _redirected_ancestor_issue(runtime_dir)
    return _runtime_permission_issue(runtime_dir, components)


def _redirected_ancestor_issue(runtime_dir: Path) -> str | None:
    """Reject a default cache reached through a redirected folder; root-owned POSIX aliases are allowed."""
    try:
        for path in runtime_dir.parents:
            info = path.lstat()
            if getattr(info, "st_file_attributes", 0) & 0x400:
                return "runtime ancestor is a reparse point"
            if stat.S_ISLNK(info.st_mode) and info.st_uid != 0:
                return "runtime ancestor is an untrusted symlink"
    except OSError:
        return "runtime trust could not be verified"
    return None


def runtime_exposure_issue(runtime_dir: Path, igor_path: Path | None) -> str | None:
    """Return how other accounts could modify a runtime, regardless of where it lives."""
    runtime_dir = Path(os.path.abspath(runtime_dir))
    components, issue = _runtime_components(runtime_dir, igor_path)
    if issue or components is None:
        return issue
    return _runtime_permission_issue(runtime_dir, components)


def _runtime_permission_issue(runtime_dir: Path, components: list[Path]) -> str | None:
    if os.name == "nt":
        from .windows_security import windows_path_trust_issue

        for path in components:
            if issue := windows_path_trust_issue(path):
                return issue
        for path in runtime_dir.parents:
            if getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                return "runtime ancestor is a reparse point"
            if issue := windows_path_trust_issue(path, ancestor=True):
                return issue
        return None
    try:
        for path in components:
            info = path.lstat()
            if info.st_uid not in {0, os.getuid()}:
                return "runtime component has an untrusted owner"
            if info.st_mode & 0o022:
                return "runtime component is writable by other accounts"
        for path in runtime_dir.parents:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                # System aliases such as macOS /var are replaceable only by root.
                if info.st_uid != 0:
                    return "runtime ancestor is an untrusted symlink"
                info = path.stat()
            if info.st_uid not in {0, os.getuid()} or not stat.S_ISDIR(info.st_mode):
                return "runtime ancestor has an untrusted owner or type"
            if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                return "runtime ancestor permits replacement by other accounts"
        return None
    except (OSError, ValueError):
        return "runtime trust could not be verified"


class RuntimeManager:
    """Manages GameMaker runtime discovery, selection, and pinning."""

    CONFIG_DIR = ".gms_mcp"
    CONFIG_FILE = "runtime.json"
    ENV_VAR = "GMS_RUNTIME_VERSION"
    RUNTIME_ROOT_ENV_VAR = "GMS_MCP_RUNTIME_ROOT"

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.discovery_diagnostics: list[str] = []
        self.exposure_warnings: list[str] = []
        # Set by select() when it had to pick a runtime the project did not record.
        self.selection_note: Optional[str] = None
        self._cached_runtimes: Optional[List[RuntimeInfo]] = None

    def list_installed(self) -> List[RuntimeInfo]:
        """Discover all installed runtimes on the system."""
        if self._cached_runtimes is not None:
            return self._cached_runtimes

        system = platform.system()
        explicit_runtime_root = os.environ.get(self.RUNTIME_ROOT_ENV_VAR)
        if explicit_runtime_root is not None:
            # An explicit root is authoritative and fail-closed: do not silently
            # scan unrelated machine-wide GameMaker installations if it is wrong.
            possible_paths = [Path(explicit_runtime_root).expanduser()]
        else:
            possible_paths = default_runtime_roots(system)

        possible_paths = list(dict.fromkeys(path.absolute() for path in possible_paths))

        runtimes = []
        warned_roots: set[Path] = set()
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

                issue = runtime_trust_issue(runtime_dir, igor_path)
                if issue:
                    self.discovery_diagnostics.append(f"Skipped untrusted runtime {runtime_dir.name}: {issue}")
                    continue
                exposed = explicit_runtime_root is None and runtime_dir.parent not in warned_roots
                if exposed and (exposure := runtime_exposure_issue(runtime_dir, igor_path)):
                    warned_roots.add(runtime_dir.parent)
                    warning = (
                        f"Other accounts can modify GameMaker's runtime cache at {runtime_dir.parent} "
                        f"({exposure}); the GameMaker IDE builds from it too. Restrict it to your account, or set "
                        f"{self.RUNTIME_ROOT_ENV_VAR} to an owner-only cache."
                    )
                    self.exposure_warnings.append(warning)
                    self.discovery_diagnostics.append(warning)

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

        assert_project_tree_contained(self.project_root)
        config_dir = self.project_root / self.CONFIG_DIR
        config_dir.mkdir(parents=True, exist_ok=True)

        config_path = config_dir / self.CONFIG_FILE
        data = {"pinned_version": version, "pinned_at": datetime.now().isoformat(), "pinned_by": "gms-mcp"}

        atomic_write_text(config_path, json.dumps(data, indent=2))

        return True

    def unpin(self) -> bool:
        """Remove runtime pin."""
        assert_project_tree_contained(self.project_root)
        config_path = self.project_root / self.CONFIG_DIR / self.CONFIG_FILE
        if config_path.exists():
            transactional_unlink(config_path)
            return True
        return False

    def select(self, version_override: Optional[str] = None) -> Optional[RuntimeInfo]:
        """Select the best runtime to use."""
        installed = self.list_installed()
        if not installed:
            return None

        self.selection_note = None
        target_version = version_override or self.get_pinned()

        if target_version:
            for r in installed:
                if r.version == target_version and r.is_valid:
                    return r
            # If pinned version not found, we could fallback, but better to return None
            # or handle it in the caller. Let's return None to signal missing specific version.
            return None

        valid = [runtime for runtime in installed if runtime.is_valid]
        recorded = self._project_recorded_versions()
        for project_version in recorded:
            for runtime in valid:
                if runtime.version == project_version:
                    return runtime
        if not valid:
            return None
        # No exact match: stay on the project's release channel (newest first), and never drift onto
        # Beta unless nothing else is installed.
        wanted_channel = classify_runtime_channel(recorded[0]) if recorded else None
        candidates = [runtime for runtime in valid if wanted_channel and runtime.release_channel == wanted_channel]
        candidates = candidates or [runtime for runtime in valid if runtime.release_channel != "beta"] or valid
        chosen = candidates[0]
        if recorded:
            note = (
                f"Project records runtime {recorded[0]} ({wanted_channel}), which is not installed; using "
                f"{chosen.version} ({chosen.release_channel}). Pin a runtime to choose explicitly."
            )
        elif len(valid) > 1:
            note = (
                f"Project records no runtime version; using {chosen.version} ({chosen.release_channel}). "
                "Pin a runtime to choose explicitly."
            )
        else:
            return chosen
        self.selection_note = note
        if note not in self.discovery_diagnostics:
            self.discovery_diagnostics.append(note)
        return chosen

    def _project_recorded_versions(self) -> list[str]:
        try:
            files = sorted(self.project_root.glob("*.yyp"))
            if len(files) != 1:
                return []
            text = files[0].read_text(encoding="utf-8")
            versions = []
            for key in ("RuntimeVersion", "IDEVersion"):
                match = re.search(r'"' + key + r'"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
                if match:
                    versions.append(match.group(1).removeprefix("runtime-"))
            return versions
        except OSError:
            return []

    def verify(self, version: Optional[str] = None) -> Dict[str, Any]:
        """Verify a runtime is valid and ready to use."""
        runtime = self.select(version)
        if not runtime:
            return {"ok": False, "issues": ["No matching runtime found.", *self.discovery_diagnostics]}

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
            "selection_note": self.selection_note,
            "discovery_diagnostics": self.discovery_diagnostics,
        }
