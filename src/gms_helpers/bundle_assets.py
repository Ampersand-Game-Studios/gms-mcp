"""Locate canonical agent bundle assets in source checkouts and built packages."""

from pathlib import Path


def bundled_assets_root() -> Path:
    """Return the complete bundled asset root for this installation mode."""
    package_bundle = Path(__file__).resolve().parent / "bundle"
    if (package_bundle / "skills" / "gms-mcp" / "SKILL.md").is_file() and (package_bundle / "hooks").is_dir():
        return package_bundle

    repository_root = Path(__file__).resolve().parents[2]
    if (repository_root / "skills" / "gms-mcp" / "SKILL.md").is_file() and (repository_root / "hooks").is_dir():
        return repository_root

    raise FileNotFoundError("The gms-mcp skill and hook bundle is missing from this installation")


def bundled_skills_dir() -> Path:
    return bundled_assets_root() / "skills"


def bundled_hooks_dir() -> Path:
    return bundled_assets_root() / "hooks"
