"""Owned macOS runner bundles and save roots for concurrent project sessions.

The stock runner derives game_save_id from its CFBundleIdentifier. A distinct archive
or cwd alone does not isolate saves. Never mutate or re-sign the installed runtime.
"""

from __future__ import annotations

import hashlib
import plistlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .agent_locks import DirectoryLock


def project_identity(project_root: str | Path) -> str:
    return hashlib.sha256(str(Path(project_root).resolve()).encode()).hexdigest()[:24]


def project_run_lock(project_root: str | Path) -> DirectoryLock:
    return DirectoryLock(
        f"game_{project_identity(project_root)}.lock",
        stale_seconds=4 * 3600,
        purpose=f"game {Path(project_root).resolve()}",
    )


@dataclass(frozen=True)
class MacRuntime:
    runner: Path
    staging: Path
    save_dir: Path
    bundle_id: str


def prepare_mac_runtime(runner: Path, project_root: Path, label: str) -> MacRuntime:
    """Make an owned signed bundle; keep its data in the bundle's actual save root.

    Save identity is stable per canonical project path. A project lease prevents two
    sessions writing these saves at once. Staging is unique even for identical labels.
    """
    bundle_id = f"com.gmsmcp.game.p{project_identity(project_root)}"
    save_dir = Path.home() / "Library" / "Application Support" / bundle_id
    save_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="session_", dir=save_dir))
    bundle = staging / "Runner.app"
    try:
        shutil.copytree(runner.parents[2], bundle, symlinks=True)
        plist_path = bundle / "Contents" / "Info.plist"
        with plist_path.open("rb") as stream:
            info = plistlib.load(stream)
        info["CFBundleIdentifier"] = bundle_id
        info["CFBundleDisplayName"] = f"{project_root.name}: {label}"
        info["CFBundleName"] = f"{project_root.name}: {label}"
        with plist_path.open("wb") as stream:
            plistlib.dump(info, stream)
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(bundle)],
            check=True,
            capture_output=True,
            text=True,
        )
        return MacRuntime(bundle / "Contents" / "MacOS" / info["CFBundleExecutable"], staging, save_dir, bundle_id)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
