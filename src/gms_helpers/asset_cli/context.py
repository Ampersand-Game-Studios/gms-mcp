from __future__ import annotations

from pathlib import Path

from ..exceptions import ProjectNotFoundError


class GameMakerContextError(Exception):
    """Raised when commands are run outside proper GameMaker context"""

    pass


def validate_gamemaker_context():
    """
    Ensure commands run in proper GameMaker project context.
    Prevents asset creation in wrong directories.
    """
    cwd = Path.cwd()

    # Check if we're in a gamemaker directory or subdirectory
    current_dir = cwd
    gamemaker_root = None

    # Walk up the directory tree looking for a GameMaker project
    while current_dir != current_dir.parent:
        # Check if this directory contains a .yyp file
        yyp_files = list(current_dir.glob("*.yyp"))
        if yyp_files:
            gamemaker_root = current_dir
            break
        current_dir = current_dir.parent

    if not gamemaker_root:
        raise GameMakerContextError(
            "ERROR: Not in a GameMaker project directory.\n"
            "GameMaker asset operations must be run from within a directory containing a .yyp project file."
        )

    # Check if we're in the project root (contains .yyp) or should be
    if gamemaker_root != cwd:
        # We found a .yyp file in a parent directory
        rel_path = cwd.relative_to(gamemaker_root)

        # If we're not in the gamemaker root, suggest the correct directory
        if str(rel_path) != ".":
            print(f"[INFO] GameMaker project found at: {gamemaker_root}")
            print(f"   Current directory: {cwd}")
            print(f"   Consider running: cd {gamemaker_root}")
            # Don't raise error, just inform - allow operations from subdirectories

    # Additional validation: check for common GameMaker directory structure
    expected_dirs = ["objects", "sprites", "scripts", "rooms"]
    missing_dirs = [d for d in expected_dirs if not (gamemaker_root / d).exists()]

    if len(missing_dirs) == len(expected_dirs):
        raise GameMakerContextError(
            f"ERROR: Directory '{gamemaker_root}' contains a .yyp file but doesn't appear to be "
            f"a valid GameMaker project (missing standard asset directories: {', '.join(expected_dirs)})"
        )

    return gamemaker_root


def validate_asset_directory_structure():
    """
    Validate that asset operations won't create files outside the GameMaker project structure.
    This prevents the bug where assets were created in the wrong location.
    """
    try:
        gamemaker_root = validate_gamemaker_context()

        # Ensure we're not creating assets outside the project structure
        cwd = Path.cwd()
        if not str(cwd).startswith(str(gamemaker_root)):
            raise GameMakerContextError(
                f"ERROR: Current directory '{cwd}' is outside GameMaker project '{gamemaker_root}'"
            )

        return gamemaker_root

    except GameMakerContextError as e:
        message = (
            f"{e}\n\n"
            "[INFO] To fix this:\n"
            "   1. Navigate to your GameMaker project directory (contains .yyp file)\n"
            "   2. Run GameMaker asset commands from within the project\n"
            "   3. Use relative paths for --parent-path arguments"
        )
        raise ProjectNotFoundError(message)
