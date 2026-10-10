"""Project registry tools: the .yyp's resources, folders, included files, configs and audio groups.

Every edit here changes only the lines of the entries involved and keeps GameMaker's own
file layout and ordering, so several agents can register assets in one project without
producing conflicting whole-file rewrites.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..mcp_types import Context
from ..project import _resolve_project_directory


def _failure(tool: str, exc: Exception) -> Dict[str, Any]:
    return {"ok": False, "tool": tool, "error": str(exc), "error_type": type(exc).__name__}


def _guard(tool: str, operation: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Turn an explained refusal into a normal failed result instead of a server traceback."""
    from gms_helpers.exceptions import GMSError

    try:
        return operation()
    except (GMSError, OSError, ValueError) as exc:
        return _failure(tool, exc)


def register_core(mcp: Any, ContextType: Any) -> None:
    """Read-only registry tools that belong to every profile."""
    globals()["Context"] = ContextType

    @mcp.tool()
    def gm_project_check(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Check the integrity of the project file (.yyp) without changing anything.

        Run this after adding, renaming or deleting assets by hand, before a build, and before a
        commit. It reports, each with the tool that fixes it:
        - assets registered but missing on disk, and assets on disk that are not registered
        - duplicate registrations, name/file mismatches, assets whose folder is not registered
        - assets left at the project root instead of in an asset-browser folder
        - included files that are registered but missing, or present under datafiles/ but unregistered
        - registry ordering (GameMaker 2026's Igor can crash on a mis-ordered .yyp) and file layout

        Returns ok=false when there are problems (things that break the IDE or a build);
        warnings alone leave ok=true.
        """
        _ = ctx
        from gms_helpers.project_config import project_setting
        from gms_helpers.yyp_registry import check_registry

        root = _resolve_project_directory(project_root)
        try:
            return check_registry(
                root, allow_root_assets=project_setting(root, "conventions.allow_root_assets", [])
            )
        except Exception as exc:  # noqa: BLE001 - reported to the caller with a remedy
            return _failure("gm_project_check", exc)


def register(mcp: Any, ContextType: Any) -> None:
    """Registry listings and mutators (part of the `assets` toolset)."""
    globals()["Context"] = ContextType

    @mcp.tool()
    def gm_included_file_list(prefix: str = "", project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """List registered included files (datafiles), optionally only those under `prefix` (e.g. datafiles/data)."""
        _ = ctx
        from gms_helpers.yyp_registry import list_included_files

        try:
            return list_included_files(_resolve_project_directory(project_root), prefix)
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_included_file_list", exc)

    @mcp.tool()
    def gm_config_list(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """List the project's build configurations (Default and its children)."""
        _ = ctx
        from gms_helpers.yyp_registry import list_configs

        try:
            return list_configs(_resolve_project_directory(project_root))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_config_list", exc)

    @mcp.tool()
    def gm_audio_group_list(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """List the project's audio groups."""
        _ = ctx
        from gms_helpers.yyp_registry import list_audio_groups

        try:
            return list_audio_groups(_resolve_project_directory(project_root))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_audio_group_list", exc)

    @mcp.tool()
    def gm_yyp_register(asset_paths: List[str], project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Register existing asset .yy files in the project file.

        Use this after creating an asset by copying another asset's folder (the gm_create_*
        tools register for you). Paths are relative to the folder containing the .yyp, e.g.
        ["scripts/my_script/my_script.yy", "objects/o_thing/o_thing.yy"]. Each .yy must exist,
        have "name"/"%Name" equal to its file name, and point at a registered parent folder.
        Only the new lines are added; nothing else in the .yyp moves.
        """
        _ = ctx
        from gms_helpers.yyp_registry import register_assets

        return _guard("gm_yyp_register", lambda: register_assets(_resolve_project_directory(project_root), asset_paths))

    @mcp.tool()
    def gm_yyp_unregister(asset_paths: List[str], project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Remove asset registrations from the project file. The files stay on disk.

        Use gm_safe_delete to delete an asset completely (it checks references first). Use
        this only to detach files you are about to remove or re-register yourself.
        """
        _ = ctx
        from gms_helpers.yyp_registry import unregister_assets

        return _guard("gm_yyp_unregister", lambda: unregister_assets(_resolve_project_directory(project_root), asset_paths))

    @mcp.tool()
    def gm_yyp_normalize_order(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Re-sort the project file's resources, folders and included files into the GameMaker 2026 IDE order.

        Only needed when gm_project_check reports an `unordered` or `non_native_layout` warning
        (another tool or a merge shuffled the file). It rewrites many lines once; tell anyone
        else editing the project before you run it.
        """
        _ = ctx
        from gms_helpers.yyp_registry import normalize_order

        return _guard("gm_yyp_normalize_order", lambda: normalize_order(_resolve_project_directory(project_root)))

    @mcp.tool()
    def gm_asset_move(
        asset_path: str, parent_path: str, project_root: str = ".", ctx: Context | None = None
    ) -> Dict[str, Any]:
        """
        Move an asset to another asset-browser folder.

        asset_path is the asset's .yy path (e.g. "scripts/foo/foo.yy"); parent_path is the
        destination folder path as registered in the project (e.g. "folders/Game/Actors.yy").
        Files on disk do not move: GameMaker folders are logical.
        """
        _ = ctx
        from gms_helpers.yyp_registry import move_asset

        return _guard("gm_asset_move", lambda: move_asset(_resolve_project_directory(project_root), asset_path, parent_path))

    @mcp.tool()
    def gm_included_file_add(
        paths: List[str],
        copy_to_mask: int | None = None,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Register files under datafiles/ as included files so they ship with the game.

        Write the file to disk first, then pass its path (e.g. "datafiles/data/items/sword.json").
        A directory path registers every file below it. Already-registered files are skipped,
        so the call is safe to repeat. copy_to_mask is GameMaker's platform mask (-1 = all
        platforms, the default taken from the project's existing entries).
        """
        _ = ctx
        from gms_helpers.yyp_registry import add_included_files

        return _guard("gm_included_file_add", lambda: add_included_files(_resolve_project_directory(project_root), paths, copy_to_mask=copy_to_mask))

    @mcp.tool()
    def gm_included_file_remove(paths: List[str], project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """
        Unregister included files (a directory path unregisters everything below it).

        The files stay on disk; delete them yourself if they are no longer wanted.
        """
        _ = ctx
        from gms_helpers.yyp_registry import remove_included_files

        return _guard("gm_included_file_remove", lambda: remove_included_files(_resolve_project_directory(project_root), paths))

    @mcp.tool()
    def gm_config_add(
        name: str, parent: str = "Default", project_root: str = ".", ctx: Context | None = None
    ) -> Dict[str, Any]:
        """Add a build configuration under `parent` (the root configuration is "Default")."""
        _ = ctx
        from gms_helpers.yyp_registry import add_config

        return _guard("gm_config_add", lambda: add_config(_resolve_project_directory(project_root), name, parent))

    @mcp.tool()
    def gm_audio_group_create(name: str, project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """Add an audio group (same settings as the project's first group). Assign sounds by editing their audioGroupId."""
        _ = ctx
        from gms_helpers.yyp_registry import add_audio_group

        return _guard("gm_audio_group_create", lambda: add_audio_group(_resolve_project_directory(project_root), name))
