"""
Base class for GameMaker asset creation
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional

from .exceptions import AssetExistsError, ProjectNotFoundError
from .utils import ensure_directory, find_yyp, load_json_loose, save_pretty_json_gm


def preflight_asset_destination(
    project_root: Path,
    *,
    asset_type: str,
    folder_prefix: str,
    name: str,
    operation: str = "create",
) -> Dict[str, Any]:
    """Return read-only evidence that a requested asset destination is unused.

    The result deliberately has no overwrite option.  Callers that receive a
    collision must obtain a replacement name and run this preflight again.
    """
    root = Path(project_root).resolve()
    asset_folder = root / folder_prefix / name.lower()
    yy_path = asset_folder / f"{name}.yy"
    relative_path = yy_path.relative_to(root).as_posix()
    collisions: list[Dict[str, str]] = []

    if asset_folder.exists():
        collisions.append({"kind": "asset_folder", "path": asset_folder.relative_to(root).as_posix()})
    elif yy_path.exists():
        collisions.append({"kind": "asset_file", "path": relative_path})
    asset_type_root = root / folder_prefix
    if asset_type_root.is_dir():
        for sibling in asset_type_root.iterdir():
            if sibling.name.casefold() == name.casefold() and sibling != asset_folder:
                collisions.append({"kind": "asset_folder", "path": sibling.relative_to(root).as_posix()})

    try:
        yyp_path = find_yyp(root)
        yyp_data = load_json_loose(yyp_path)
    except ProjectNotFoundError:
        # BaseAsset is also a low-level file factory used by isolated tests and
        # import flows. Without a project index we can still safely reject an
        # on-disk collision, but cannot inspect resource registrations.
        available = not collisions
        return {
            "ok": available,
            "available": available,
            "operation": operation,
            "asset_type": asset_type,
            "requested_name": name,
            "destination_path": relative_path,
            "replacement_name_required": not available,
            "replacement_name": None,
            "overwrite_supported": False,
            "project_index_available": False,
            "collisions": collisions,
        }
    except Exception as exc:
        return {
            "ok": False,
            "available": False,
            "operation": operation,
            "asset_type": asset_type,
            "requested_name": name,
            "replacement_name_required": False,
            "error": f"Could not inspect project resources: {exc}",
            "collisions": collisions,
        }

    if not isinstance(yyp_data, dict):
        return {
            "ok": False,
            "available": False,
            "operation": operation,
            "asset_type": asset_type,
            "requested_name": name,
            "replacement_name_required": False,
            "error": f"Could not inspect project resources in {yyp_path.name}",
            "collisions": collisions,
        }

    for entry in yyp_data.get("resources", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), dict):
            continue
        resource = entry["id"]
        existing_name = resource.get("name")
        existing_path = str(resource.get("path", "")).replace("\\", "/")
        if isinstance(existing_name, str) and existing_name.casefold() == name.casefold():
            collisions.append({"kind": "resource_name", "path": existing_path})
        elif existing_path.casefold() == relative_path.casefold():
            collisions.append({"kind": "resource_path", "path": existing_path})

    available = not collisions
    return {
        "ok": available,
        "available": available,
        "operation": operation,
        "asset_type": asset_type,
        "requested_name": name,
        "destination_path": relative_path,
        "replacement_name_required": not available,
        "replacement_name": None,
        "overwrite_supported": False,
        "collisions": collisions,
    }


def require_asset_destination_available(**kwargs: Any) -> Dict[str, Any]:
    """Raise before mutation when a destination preflight finds a collision."""
    evidence = preflight_asset_destination(**kwargs)
    if not evidence["available"]:
        if evidence.get("replacement_name_required"):
            raise AssetExistsError(
                f"Asset destination collision for '{evidence['requested_name']}'; "
                "provide a replacement name. Existing assets are never overwritten."
            )
        raise AssetExistsError(str(evidence.get("error") or "Asset destination is unavailable."))
    return evidence


class BaseAsset(ABC):
    """Base class for all GameMaker asset types."""

    # Override these in subclasses
    kind: str = "base"
    folder_prefix: str = "unknown"
    gm_tag: str = "GMUnknown"

    def __init__(self):
        pass

    @abstractmethod
    def create_yy_data(self, name: str, parent_path: str, **kwargs) -> Dict[str, Any]:
        """Create the .yy JSON data for this asset type."""
        pass

    @abstractmethod
    def create_stub_files(self, asset_folder: Path, name: str, **kwargs):
        """Create any additional files (like .gml files for scripts)."""
        pass

    def get_folder_path(self, project_root: Path, name: str) -> Path:
        """Get the full path where this asset should be created."""
        # All physical folders are stored on disk in *lower-case* to avoid
        # cross-platform case-sensitivity headaches (e.g. Linux CI runners).
        # File names (.yy, .gml, etc.) retain their original GameMaker-style
        # casing, only the directory slug is normalised.
        return project_root / self.folder_prefix / name.lower()

    def get_yy_path(self, asset_folder: Path, name: str) -> Path:
        """Get the path for the .yy file."""
        return asset_folder / f"{name}.yy"

    def create_files(self, project_root: Path, name: str, parent_path: str, **kwargs) -> str:
        """
        Create all files for this asset type.
        Returns the relative path to the .yy file for .yyp insertion.
        """
        project_root = Path(project_root).resolve()
        require_asset_destination_available(
            project_root=project_root,
            asset_type=self.kind,
            folder_prefix=self.folder_prefix,
            name=name,
            operation="create",
        )

        # Omitted parents are resolved to a logical folder before any asset files
        # are written. GameMaker project roots are never used as implicit parents.
        if not parent_path:
            from .utils import ensure_default_asset_parent

            parent_path = ensure_default_asset_parent(project_root, self.kind, self.folder_prefix)

        # Create the asset folder
        asset_folder = self.get_folder_path(project_root, name)
        ensure_directory(asset_folder)

        # Create the .yy file
        yy_path = self.get_yy_path(asset_folder, name)
        yy_data = self.create_yy_data(name, parent_path, **kwargs)

        # Match existing project conventions for $GM* version strings.
        # Many projects use "" or "v1" depending on the GameMaker version / migration history.
        try:
            from .utils import detect_asset_format_version

            detected = detect_asset_format_version(project_root, self.folder_prefix)
            if detected is not None:
                gm_key = f"${self.gm_tag}"
                if isinstance(yy_data, dict) and gm_key in yy_data:
                    # Preserve dict key order by updating the existing key in-place.
                    yy_data[gm_key] = detected
        except Exception:
            # Best-effort only: never block asset creation.
            pass
        save_pretty_json_gm(yy_path, yy_data)
        print(f"Created {yy_path.relative_to(project_root)}")

        # Create stub files
        self.create_stub_files(asset_folder, name, **kwargs)

        # Return relative path for .yyp insertion
        return yy_path.relative_to(project_root).as_posix()

    def validate_name(self, name: str) -> bool:
        """Validate asset name according to GameMaker conventions."""
        # Basic validation - can be overridden in subclasses
        if not name:
            return False
        if not name.replace("_", "").replace("-", "").isalnum():
            return False
        return True

    def get_parent_name(self, parent_path: str) -> str:
        """Extract parent folder name from path."""
        return Path(parent_path).stem
