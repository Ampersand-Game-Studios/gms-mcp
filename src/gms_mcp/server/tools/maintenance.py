from __future__ import annotations

import argparse
from typing import Any, Dict, List

from ..dispatch import _run_for_data, _run_with_fallback
from ..dry_run_policy import _dry_run_policy_blocked_result, _requires_dry_run_for_tool
from ..mcp_types import Context
from ..project import _ensure_cli_on_sys_path, _resolve_repo_root
from ..tool_types import OutputMode


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    # -----------------------------
    # Maintenance tools
    # -----------------------------
    @mcp.tool()
    async def gm_maintenance_auto(
        fix: bool = False,
        verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Run your auto-maintenance pipeline."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_auto

        args = argparse.Namespace(
            fix=fix,
            verbose=verbose,
            project_root=project_root,
        )
        cli_args = ["maintenance", "auto"]
        if fix:
            cli_args.append("--fix")
        cli_args.append("--verbose" if verbose else "--no-verbose")
        if fix and _requires_dry_run_for_tool("gm_maintenance_auto"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_auto",
                "Use fix=false, add gm_maintenance_auto to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_maintenance_auto,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_lint(
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Lint the project (JSON and naming) and return every issue found, info level included.

        The issues are grouped as gm_diagnostics groups them: each message once ({name} is the
        affected file's own name), `assets` mapping a folder to asset names whose files are
        <folder>/<name>/<name>.yy, and `files` mapping a folder to any other file names.
        """
        _ = ctx
        from gms_helpers.commands.diagnostics_commands import dense_diagnostics
        from gms_helpers.commands.maintenance_commands import handle_maintenance_lint

        return await _run_for_data(
            direct_handler=handle_maintenance_lint,
            direct_args=argparse.Namespace(project_root=project_root),
            project_root=project_root,
            tool_name="maintenance-lint",
            cli_args=["maintenance", "lint"],
            shape=dense_diagnostics,
        )

    @mcp.tool()
    async def gm_maintenance_validate_json(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Validate JSON files in the project."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_validate_json

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["maintenance", "validate-json"]

        return await _run_with_fallback(
            direct_handler=handle_maintenance_validate_json,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_list_orphans(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Find orphaned and missing assets."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_list_orphans

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["maintenance", "list-orphans"]

        return await _run_with_fallback(
            direct_handler=handle_maintenance_list_orphans,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_prune_missing(
        dry_run: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove missing asset references from project file (previews by default; pass dry_run=false to write)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_prune_missing

        args = argparse.Namespace(dry_run=dry_run, project_root=project_root)
        cli_args = ["maintenance", "prune-missing"]
        if dry_run:
            cli_args.append("--dry-run")
        if not dry_run and _requires_dry_run_for_tool("gm_maintenance_prune_missing"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_prune_missing",
                "Use dry_run=true, add gm_maintenance_prune_missing to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_maintenance_prune_missing,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_validate_paths(
        strict_disk_check: bool = False,
        include_parent_folders: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Check that every asset-browser folder an asset names exists, and find folders nothing uses.

        `issues` groups the problems by severity and type; an orphaned folder is listed by its
        folder path alone.
        """
        _ = ctx
        from gms_helpers.commands.maintenance_commands import dense_path_issues, handle_maintenance_validate_paths

        args = argparse.Namespace(
            strict_disk_check=strict_disk_check,
            include_parent_folders=include_parent_folders,
            project_root=project_root,
        )
        return await _run_for_data(
            direct_handler=handle_maintenance_validate_paths,
            direct_args=args,
            project_root=project_root,
            tool_name="maintenance-validate-paths",
            cli_args=["maintenance", "validate-paths"],
            shape=dense_path_issues,
        )

    @mcp.tool()
    async def gm_maintenance_dedupe_resources(
        auto: bool = True,
        dry_run: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove duplicate resource entries from .yyp (previews by default; pass dry_run=false to write)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_dedupe_resources

        args = argparse.Namespace(auto=auto, dry_run=dry_run, project_root=project_root)
        cli_args = ["maintenance", "dedupe-resources"]
        if auto:
            cli_args.append("--auto")
        if dry_run:
            cli_args.append("--dry-run")
        if not dry_run and _requires_dry_run_for_tool("gm_maintenance_dedupe_resources"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_dedupe_resources",
                "Use dry_run=true, add gm_maintenance_dedupe_resources to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_maintenance_dedupe_resources,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_sync_events(
        fix: bool = False,
        object: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Synchronize object events (dry-run unless fix=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_sync_events

        args = argparse.Namespace(fix=fix, object=object if object else None, project_root=project_root)
        cli_args = ["maintenance", "sync-events"]
        if fix:
            cli_args.append("--fix")
        if object:
            cli_args.extend(["--object", object])
        if fix and _requires_dry_run_for_tool("gm_maintenance_sync_events"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_sync_events",
                "Use fix=false, add gm_maintenance_sync_events to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_maintenance_sync_events,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_normalize_names(
        fix: bool = False,
        asset_type: str = "",
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Plan (fix=false) or apply naming-convention asset renames.

        Renames are grouped by the asset's folder as "old -> new"; the asset's file is
        <folder>/<old>/<old>.yy.
        """
        _ = ctx
        from gms_helpers.commands.maintenance_commands import dense_renames, handle_maintenance_normalize_names

        if fix and _requires_dry_run_for_tool("gm_maintenance_normalize_names"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_normalize_names",
                "Use fix=false, add gm_maintenance_normalize_names to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )
        args = argparse.Namespace(fix=fix, asset_type=asset_type or None, project_root=project_root)
        return await _run_for_data(
            direct_handler=handle_maintenance_normalize_names,
            direct_args=args,
            project_root=project_root,
            tool_name="maintenance-normalize-names",
            cli_args=["maintenance", "normalize-names"],
            shape=dense_renames,
        )

    @mcp.tool()
    async def gm_maintenance_clean_old_files(
        delete: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove .old.yy backup files (dry-run unless delete=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_clean_old_files

        args = argparse.Namespace(delete=delete, project_root=project_root)
        cli_args = ["maintenance", "clean-old-files"]
        if delete:
            cli_args.append("--delete")
        if delete and _requires_dry_run_for_tool("gm_maintenance_clean_old_files"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_clean_old_files",
                "Use delete=false (dry-run), add gm_maintenance_clean_old_files to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_maintenance_clean_old_files,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_clean_orphans(
        delete: bool = False,
        skip_types: List[str] | None = None,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Remove orphaned asset files (dry-run unless delete=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_clean_orphans

        skip_types_value = skip_types if skip_types is not None else ["folder"]
        args = argparse.Namespace(delete=delete, skip_types=skip_types_value, project_root=project_root)
        cli_args = ["maintenance", "clean-orphans"]
        if delete:
            cli_args.append("--delete")
        if skip_types is not None:
            cli_args.append("--skip-types")
            cli_args.extend(skip_types_value)
        if delete and _requires_dry_run_for_tool("gm_maintenance_clean_orphans"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_clean_orphans",
                "Use delete=false (dry-run), add gm_maintenance_clean_orphans to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_maintenance_clean_orphans,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

    @mcp.tool()
    async def gm_maintenance_fix_issues(
        verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Run comprehensive maintenance with fixes enabled."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_fix_issues

        args = argparse.Namespace(verbose=verbose, project_root=project_root)
        cli_args = ["maintenance", "fix-issues"]
        if verbose:
            cli_args.append("--verbose")
        if _requires_dry_run_for_tool("gm_maintenance_fix_issues"):
            return _dry_run_policy_blocked_result(
                "gm_maintenance_fix_issues",
                "Run diagnostics/lint without fixes, add gm_maintenance_fix_issues to GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST, or unset GMS_MCP_REQUIRE_DRY_RUN for this session.",
            )

        return await _run_with_fallback(
            direct_handler=handle_maintenance_fix_issues,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )
