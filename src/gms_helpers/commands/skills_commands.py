"""Skills command implementations for installing Claude Code skills."""

import shutil
from pathlib import Path
from typing import Dict, Any


def get_skills_source_dir() -> Path:
    """Return the path to the bundled skills directory."""
    # Priority 1: plugin directory (when running from repo or plugin installed)
    repo_root = Path(__file__).parent.parent.parent.parent
    plugin_skills = repo_root / "plugin" / "skills"
    if plugin_skills.exists():
        return plugin_skills

    # Priority 2: installed package location
    pkg_skills = Path(__file__).parent.parent / "skills"
    if pkg_skills.exists():
        return pkg_skills

    raise FileNotFoundError("Skills directory not found")


def get_target_dir(project: bool = False) -> Path:
    """
    Return the target directory for skills installation.

    Args:
        project: If True, install to ./.claude/skills/gms-mcp/
                 If False, install to ~/.claude/skills/gms-mcp/
    """
    if project:
        return Path.cwd() / ".claude" / "skills" / "gms-mcp"
    else:
        return Path.home() / ".claude" / "skills" / "gms-mcp"


def handle_skills_install(args) -> Dict[str, Any]:
    """
    Install Claude Code skills to the user's skills directory.

    Copies all skills from the package to either:
    - ~/.claude/skills/gms-mcp/ (default)
    - ./.claude/skills/gms-mcp/ (with --project flag)
    """
    source_dir = get_skills_source_dir() / "gms-mcp"
    target_dir = get_target_dir(project=getattr(args, 'project', False))
    force = getattr(args, 'force', False)

    if not source_dir.exists():
        print(f"[ERROR] Skills source directory not found: {source_dir}")
        return {"success": False, "error": "Skills source not found"}

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
                skipped.append(str(relative_path))
            else:
                shutil.copy2(source_file, target_file)
                copied.append(str(relative_path))

    # Report results
    if copied:
        print(f"[OK]    Installed {len(copied)} skill file(s) to {target_dir}")
        for f in copied:
            print(f"        + {f}")

    if skipped:
        print(f"[SKIP]  {len(skipped)} file(s) already exist (use --force to overwrite)")
        for f in skipped:
            print(f"        - {f}")

    if not copied and not skipped:
        print("[WARN]  No skill files found to install")

    return {
        "success": True,
        "target_dir": str(target_dir),
        "copied": copied,
        "skipped": skipped
    }


def handle_skills_list(args) -> Dict[str, Any]:
    """
    List available skills and their installation status.
    """
    source_dir = get_skills_source_dir() / "gms-mcp"
    user_dir = get_target_dir(project=False)
    project_dir = get_target_dir(project=True)

    installed_only = getattr(args, 'installed', False)

    skills = []

    if not source_dir.exists():
        print("[WARN]  No skills bundled with this package")
        return {"success": True, "skills": []}

    # Gather all skill files
    for source_file in source_dir.rglob("*.md"):
        relative_path = source_file.relative_to(source_dir)

        user_installed = (user_dir / relative_path).exists()
        project_installed = (project_dir / relative_path).exists()

        skill_info = {
            "name": str(relative_path),
            "user_installed": user_installed,
            "project_installed": project_installed
        }

        if installed_only and not (user_installed or project_installed):
            continue

        skills.append(skill_info)

    # Print results
    print("Available gms-mcp skills:")
    print()

    for skill in sorted(skills, key=lambda s: s["name"]):
        status = []
        if skill["user_installed"]:
            status.append("user")
        if skill["project_installed"]:
            status.append("project")

        status_str = f" [{', '.join(status)}]" if status else ""
        print(f"  {skill['name']}{status_str}")

    if not skills:
        print("  (no skills found)")

    print()
    print(f"User skills dir:    {user_dir}")
    print(f"Project skills dir: {project_dir}")

    return {
        "success": True,
        "skills": skills,
        "user_dir": str(user_dir),
        "project_dir": str(project_dir)
    }


def handle_skills_uninstall(args) -> Dict[str, Any]:
    """
    Remove installed skills from the target directory.
    """
    target_dir = get_target_dir(project=getattr(args, 'project', False))

    if not target_dir.exists():
        print(f"[OK]    No skills installed at {target_dir}")
        return {"success": True, "removed": False}

    # Count files before removal
    file_count = sum(1 for _ in target_dir.rglob("*") if _.is_file())

    # Remove the entire gms-mcp skills directory
    shutil.rmtree(target_dir)

    print(f"[OK]    Removed {file_count} skill file(s) from {target_dir}")

    return {
        "success": True,
        "removed": True,
        "target_dir": str(target_dir),
        "file_count": file_count
    }
