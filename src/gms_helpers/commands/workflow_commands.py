"""Workflow command implementations."""

from pathlib import Path

from ..workflow import duplicate_asset, rename_asset, delete_asset, swap_sprite_png

def handle_workflow_duplicate(args):
    """Handle asset duplication."""
    project_root = Path(args.project_root).resolve()
    result = duplicate_asset(project_root, args.asset_path, args.new_name, yes=getattr(args, 'yes', False))
    return result

def handle_workflow_rename(args):
    """Handle asset renaming."""
    project_root = Path(args.project_root).resolve()
    result = rename_asset(project_root, args.asset_path, args.new_name)
    return result

def handle_workflow_delete(args):
    """Handle asset deletion."""
    project_root = Path(args.project_root).resolve()
    result = delete_asset(project_root, args.asset_path, dry_run=getattr(args, 'dry_run', False))
    return result

def handle_workflow_swap_sprite(args):
    """Handle sprite PNG swapping."""
    project_root = Path(args.project_root).resolve()
    result = swap_sprite_png(project_root, args.asset_path, Path(args.png))
    return result
