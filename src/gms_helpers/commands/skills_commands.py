"""Skills command implementations for installing agent skills."""

import json
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..bundle_assets import bundled_skills_dir

# Written into each install target; uninstall removes only the files it lists.
INSTALL_MANIFEST_NAME = ".gms-mcp-install.json"


def get_skills_source_dir() -> Path:
    """Return the path to the bundled skills directory."""
    return bundled_skills_dir()


def _platform_name(openclaw: bool) -> str:
    return "OpenClaw" if openclaw else "Claude Code"


def get_target_dir(project: bool = False, *, openclaw: bool = False) -> Path:
    """
    Return the target directory for skills installation.

    Args:
        project: If True, install in the current workspace.
                 If False, install in the user's home config directory.
        openclaw: If True, target OpenClaw skill directories instead of Claude.
    """
    if openclaw and project:
        # OpenClaw loads workspace skills from ./skills/
        return Path.cwd() / "skills" / "gms-mcp"
    dot_dir = ".openclaw" if openclaw else ".claude"
    if project:
        return Path.cwd() / dot_dir / "skills" / "gms-mcp"
    else:
        return Path.home() / dot_dir / "skills" / "gms-mcp"


def _legacy_openclaw_project_dir(*, openclaw: bool, project: bool) -> Path | None:
    """Return legacy OpenClaw workspace path if this invocation targets it."""
    if openclaw and project:
        return Path.cwd() / ".openclaw" / "skills" / "gms-mcp"
    return None


def _overlaps(first: Path, second: Path) -> bool:
    """True when either directory is, or contains, the other."""
    a, b = first.resolve(), second.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _read_install_manifest(target_dir: Path) -> Optional[List[str]]:
    manifest_path = target_dir / INSTALL_MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise ValueError(f"Malformed skills install manifest: {manifest_path}")
    return files


def _write_install_manifest(target_dir: Path, files: List[str]) -> None:
    payload = {"installer": "gms-mcp skills install", "files": sorted(set(files))}
    (target_dir / INSTALL_MANIFEST_NAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _manifest_file_path(target_dir: Path, relative: str) -> Optional[Path]:
    candidate = (target_dir / relative).resolve()
    if not candidate.is_relative_to(target_dir.resolve()) or candidate == target_dir.resolve():
        return None
    return candidate


def handle_skills_install(args) -> Dict[str, Any]:
    """
    Install skills to the selected agent's skills directory.

    Copies all skills from the package to either:
    - ~/.claude/skills/gms-mcp/ or ./.claude/skills/gms-mcp/ (default)
    - ~/.openclaw/skills/gms-mcp/ or ./skills/gms-mcp/ (--openclaw)
    """
    source_dir = get_skills_source_dir() / "gms-mcp"
    openclaw = bool(getattr(args, "openclaw", False))
    project = bool(getattr(args, "project", False))
    target_dir = get_target_dir(project=project, openclaw=openclaw)
    legacy_dir = _legacy_openclaw_project_dir(openclaw=openclaw, project=project)
    force = getattr(args, "force", False)

    if not source_dir.exists():
        print(f"[ERROR] Skills source directory not found: {source_dir}")
        return {"success": False, "error": "Skills source not found"}

    if _overlaps(target_dir, source_dir):
        message = f"Install target {target_dir} overlaps the bundled skills source {source_dir}"
        print(f"[ERROR] {message}")
        return {"success": False, "error": message}

    # Create target directory structure
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    skipped = []

    # Copy all files from source to target
    for source_file in source_dir.rglob("*"):
        if source_file.is_file():
            relative_path = source_file.relative_to(source_dir)
            target_file = target_dir / relative_path

            # Create parent directories if needed
            target_file.parent.mkdir(parents=True, exist_ok=True)

            if target_file.exists() and not force:
                skipped.append(relative_path.as_posix())
            else:
                shutil.copy2(source_file, target_file)
                copied.append(relative_path.as_posix())

    # Record what this installer owns. Skipped files stay owned only if an earlier
    # install recorded them; a pre-existing user file never becomes removable.
    previous = _read_install_manifest(target_dir) or []
    owned = copied + [path for path in skipped if path in previous]
    if owned:
        _write_install_manifest(target_dir, owned + [path for path in previous if path not in owned])

    # Report results
    if copied:
        print(f"[OK]    Installed {len(copied)} {_platform_name(openclaw)} skill file(s) to {target_dir}")
        for f in copied:
            print(f"        + {f}")

    if skipped:
        print(f"[SKIP]  {len(skipped)} file(s) already exist (use --force to overwrite)")
        for f in skipped:
            print(f"        - {f}")

    if legacy_dir and legacy_dir.exists():
        print(f"[INFO]  Legacy OpenClaw workspace skills path detected: {legacy_dir}")
        print(f"        New installs use: {target_dir}")

    if not copied and not skipped:
        print("[WARN]  No skill files found to install")

    return {"success": True, "target_dir": str(target_dir), "copied": copied, "skipped": skipped}


def handle_skills_list(args) -> Dict[str, Any]:
    """
    List available skills and their installation status.
    """
    source_dir = get_skills_source_dir() / "gms-mcp"
    openclaw = bool(getattr(args, "openclaw", False))
    user_dir = get_target_dir(project=False, openclaw=openclaw)
    project_dir = get_target_dir(project=True, openclaw=openclaw)
    legacy_project_dir = _legacy_openclaw_project_dir(openclaw=openclaw, project=True)

    installed_only = getattr(args, "installed", False)

    skills = []

    if not source_dir.exists():
        print("[WARN]  No skills bundled with this package")
        return {"success": True, "skills": []}

    # Gather all skill files
    for source_file in source_dir.rglob("*.md"):
        relative_path = source_file.relative_to(source_dir)

        user_installed = (user_dir / relative_path).exists()
        project_installed = (project_dir / relative_path).exists()
        legacy_project_installed = bool(legacy_project_dir and (legacy_project_dir / relative_path).exists())

        skill_info = {
            "name": relative_path.as_posix(),
            "user_installed": user_installed,
            "project_installed": project_installed,
            "legacy_project_installed": legacy_project_installed,
        }

        if installed_only and not (user_installed or project_installed or legacy_project_installed):
            continue

        skills.append(skill_info)

    # Print results
    print(f"Available gms-mcp skills ({_platform_name(openclaw)}):")
    print()

    for skill in sorted(skills, key=lambda s: s["name"]):
        status = []
        if skill["user_installed"]:
            status.append("user")
        if skill["project_installed"]:
            status.append("project")
        if skill["legacy_project_installed"]:
            status.append("legacy-project")

        status_str = f" [{', '.join(status)}]" if status else ""
        print(f"  {skill['name']}{status_str}")

    if not skills:
        print("  (no skills found)")

    print()
    print(f"User skills dir:    {user_dir}")
    print(f"Project skills dir: {project_dir}")
    if legacy_project_dir is not None:
        print(f"Legacy skills dir:  {legacy_project_dir}")
        if legacy_project_dir.exists():
            print("[WARN]  Legacy OpenClaw workspace skills detected; migrate to ./skills/gms-mcp.")

    return {
        "success": True,
        "skills": skills,
        "user_dir": str(user_dir),
        "project_dir": str(project_dir),
        "legacy_project_dir": str(legacy_project_dir) if legacy_project_dir else None,
    }


def handle_skills_uninstall(args) -> Dict[str, Any]:
    """
    Remove installed skill files from the target directory.

    Only files listed in the install manifest are removed; files a user added to
    the directory are kept, and a directory overlapping the bundled skills
    source (e.g. ``./skills/gms-mcp`` in this repository) is never touched.
    """
    openclaw = bool(getattr(args, "openclaw", False))
    project = bool(getattr(args, "project", False))
    target_dir = get_target_dir(project=project, openclaw=openclaw)
    legacy_dir = _legacy_openclaw_project_dir(openclaw=openclaw, project=project)
    target_dirs = [target_dir]
    if legacy_dir is not None:
        target_dirs.append(legacy_dir)
    existing_dirs = [d for d in target_dirs if d.exists()]

    if not existing_dirs:
        if legacy_dir is not None:
            print(f"[OK]    No skills installed at {target_dir} or {legacy_dir}")
        else:
            print(f"[OK]    No skills installed at {target_dir}")
        return {"success": True, "removed": False}

    source_dir = get_skills_source_dir() / "gms-mcp"
    for directory in existing_dirs:
        if _overlaps(directory, source_dir):
            message = f"Refusing to uninstall from {directory}: it overlaps the bundled skills source {source_dir}"
            print(f"[ERROR] {message}")
            return {"success": False, "error": message}

    file_count = 0
    removed_dirs: List[str] = []
    kept: Dict[str, List[str]] = {}
    unmanaged: List[str] = []
    for directory in existing_dirs:
        manifest = _read_install_manifest(directory)
        if manifest is None:
            unmanaged.append(str(directory))
            print(f"[SKIP]  {directory} has no install manifest; nothing removed (remove it manually if unwanted)")
            continue
        for relative in manifest:
            file_path = _manifest_file_path(directory, relative)
            if file_path is not None and file_path.is_file():
                file_path.unlink()
                file_count += 1
        (directory / INSTALL_MANIFEST_NAME).unlink()
        # Remove directories left empty, deepest first; keep anything still holding user files.
        for sub in sorted((p for p in directory.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(sub.iterdir()):
                sub.rmdir()
        if any(directory.iterdir()):
            kept[str(directory)] = sorted(
                p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()
            )
        else:
            directory.rmdir()
            removed_dirs.append(str(directory))

    print(f"[OK]    Removed {file_count} {_platform_name(openclaw)} skill file(s)")
    for directory in removed_dirs:
        print(f"        - {directory}")
    for directory, files in kept.items():
        print(f"[INFO]  Kept {len(files)} file(s) not installed by gms-mcp in {directory}")

    return {
        "success": True,
        "removed": file_count > 0,
        "target_dir": str(target_dir),
        "removed_dirs": removed_dirs,
        "file_count": file_count,
        "kept_files": kept,
        "unmanaged_dirs": unmanaged,
    }
