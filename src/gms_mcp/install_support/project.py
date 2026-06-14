from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from .naming import PROJECT_CONFIG_FILE, create_default_config_file


def _setup_project_config(
    *,
    gm_project_root: Path,
    non_interactive: bool,
    skip_config: bool,
    use_defaults: bool,
    dry_run: bool,
) -> Optional[Path]:
    """
    Set up the .gms-mcp.json configuration file for naming conventions.

    Args:
        gm_project_root: Path to the GameMaker project directory
        non_interactive: If True, never prompt for input
        skip_config: If True, skip config setup entirely
        use_defaults: If True, create config with defaults (no prompts)
        dry_run: If True, don't write any files

    Returns:
        Path to created config file, or None if skipped
    """
    if skip_config:
        return None

    config_path = gm_project_root / PROJECT_CONFIG_FILE

    # Check if config already exists
    if config_path.exists():
        print(f"[INFO] Project config already exists: {config_path}")
        return config_path

    # Determine whether to create config
    should_create = use_defaults

    if not should_create and not non_interactive and sys.stdin and sys.stdin.isatty():
        # Interactive mode - ask user
        print("\n" + "=" * 60)
        print("NAMING CONVENTIONS CONFIGURATION")
        print("=" * 60)
        print("\nThe GMS-MCP tool can enforce naming conventions for assets.")
        print("Default prefixes:")
        print("  - Objects:  o_       (e.g., o_player)")
        print("  - Sprites:  spr_     (e.g., spr_player)")
        print("  - Rooms:    r_       (e.g., r_main)")
        print("  - Scripts:  snake_case (constructors can be PascalCase)")
        print("\nYou can customize these in the config file after creation.")
        print("")

        while True:
            choice = input("Create .gms-mcp.json config file? [Y/n]: ").strip().lower()
            if choice in ("", "y", "yes"):
                should_create = True
                break
            elif choice in ("n", "no"):
                should_create = False
                break
            else:
                print("[ERROR] Please enter Y or N.")
    elif not should_create and non_interactive:
        # Non-interactive mode without --use-defaults: skip by default
        print("[INFO] Skipping config file creation (non-interactive mode).")
        print("       Use --use-defaults to create config with default settings.")
        return None

    if not should_create:
        print("[INFO] Skipping config file creation.")
        return None

    if dry_run:
        print(f"[DRY-RUN] Would create: {config_path}")
        return config_path

    try:
        created_path = create_default_config_file(gm_project_root, overwrite=False)
        print(f"[OK] Created project config: {created_path}")
        print("     Edit this file to customize naming conventions.")
        return created_path
    except FileExistsError:
        print(f"[INFO] Config file already exists: {config_path}")
        return config_path
    except Exception as e:
        print(f"[WARN] Could not create config file: {e}")
        return None

