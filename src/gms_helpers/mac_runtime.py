"""Owned macOS runner bundles and save roots for concurrent project sessions.

The stock runner derives game_save_id from its CFBundleIdentifier. A distinct archive
or cwd alone does not isolate saves. Never mutate or re-sign the installed runtime.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .agent_locks import DirectoryLock


CODESIGN_TIMEOUT_SECONDS = 300


def _canonical_project_path(project_root: str | Path) -> str:
    """The project path as the volume stores it, so differently-cased spellings share one identity.

    macOS volumes are usually case-insensitive and ``resolve()`` keeps the caller's spelling;
    F_GETPATH returns the on-disk spelling. Windows paths are case-insensitive, so normcase them.
    """
    resolved = Path(project_root).resolve()
    if sys.platform == "darwin":
        import fcntl

        try:
            descriptor = os.open(resolved, os.O_RDONLY)
        except OSError:
            return str(resolved)
        try:
            raw = fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytes(1024))
            return os.fsdecode(raw.split(b"\0", 1)[0]) or str(resolved)
        except OSError:
            return str(resolved)
        finally:
            os.close(descriptor)
    return os.path.normcase(str(resolved))


def project_identity(project_root: str | Path) -> str:
    return hashlib.sha256(_canonical_project_path(project_root).encode()).hexdigest()[:24]


def project_run_lock(project_root: str | Path) -> DirectoryLock:
    return DirectoryLock(
        f"game_{project_identity(project_root)}.lock",
        stale_seconds=4 * 3600,
        purpose=f"game {Path(project_root).resolve()}",
    )


def mac_retina_enabled(project_root: str | Path) -> bool | None:
    """The project's macOS "Enable Retina" option (options/mac/options_mac.yy), or None when it has none.

    The stock runner reads it only from its bundle's Info.plist (YYMacUseRetina), and the run path never puts it
    there, so a run without this key draws at half resolution on a Retina screen and is scaled up.
    """
    path = Path(project_root) / "options" / "mac" / "options_mac.yy"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'"option_mac_enable_retina"\s*:\s*(true|false)', text)
    return None if match is None else match.group(1) == "true"


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
    from .runtime_manager import runtime_trust_issue

    for parent in runner.parents:
        if parent.name.startswith("runtime-"):
            issue = runtime_trust_issue(parent, runner)
            if issue:
                raise OSError(f"Untrusted GameMaker runtime: {issue}")
            break
    bundle_id = f"com.gmsmcp.game.p{project_identity(project_root)}"
    save_dir = Path.home() / "Library" / "Application Support" / bundle_id
    save_dir.mkdir(parents=True, exist_ok=True)
    _remove_abandoned_staging(project_root, save_dir)
    staging = Path(tempfile.mkdtemp(prefix="session_", dir=save_dir))
    bundle = staging / "Runner.app"
    try:
        # Dereference bundle links into the private copy before editing or signing.
        # A linked Info.plist (or Contents directory) must never write through to
        # the installed runtime.
        shutil.copytree(runner.parents[2], bundle, symlinks=False)
        plist_path = bundle / "Contents" / "Info.plist"
        with plist_path.open("rb") as stream:
            info = plistlib.load(stream)
        executable = info.get("CFBundleExecutable")
        if (
            not isinstance(executable, str)
            or not executable
            or executable in {".", ".."}
            or "/" in executable
            or "\\" in executable
        ):
            raise ValueError("The runner bundle has an invalid executable name")
        info["CFBundleIdentifier"] = bundle_id
        info["CFBundleDisplayName"] = f"{project_root.name}: {label}"
        info["CFBundleName"] = f"{project_root.name}: {label}"
        retina = mac_retina_enabled(project_root)
        if retina is not None:
            info["YYMacUseRetina"] = retina
        with plist_path.open("wb") as stream:
            plistlib.dump(info, stream)
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(bundle)],
            check=True,
            capture_output=True,
            text=True,
            timeout=CODESIGN_TIMEOUT_SECONDS,
        )
        return MacRuntime(bundle / "Contents" / "MacOS" / executable, staging, save_dir, bundle_id)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _remove_abandoned_staging(project_root: Path, save_dir: Path) -> None:
    """Delete runner copies left by a process killed before its own cleanup ran.

    Callers hold the project lease, so no other session of this project is running; only the
    staging that the persisted session still references (archived later) is kept.
    """
    from .run_session import RunSessionManager

    persisted = RunSessionManager(project_root).get_current_session()
    keep = Path(persisted.exe_path).parent if persisted is not None and persisted.isolated_runtime else None
    for path in save_dir.glob("session_*"):
        if path.is_dir() and not path.is_symlink() and path != keep:
            shutil.rmtree(path, ignore_errors=True)
