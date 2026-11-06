#!/usr/bin/env python3
"""
GMS Agent Auto-Setup Helper
Automatically sets up the gms command for AI agents (Cursor and other MCP-capable clients).
"""

import os
import sys
import subprocess
import platform
import shlex
import shutil
from pathlib import Path
from .exceptions import GMSError


def detect_shell():
    """Detect the current shell environment."""
    # Check if we're in PowerShell
    if os.environ.get("PSModulePath"):
        return "powershell"
    # Check for bash/zsh
    elif os.environ.get("BASH_VERSION") or os.environ.get("ZSH_VERSION"):
        return "bash"
    # Default based on platform
    elif platform.system() == "Windows":
        return "powershell"
    else:
        return "bash"


def test_gms_command():
    """Test if gms command is already available."""
    try:
        executable = next(
            (
                found
                for directory in os.environ.get("PATH", "").split(os.pathsep)
                if directory and Path(directory).is_absolute() and Path(directory).resolve() != Path.cwd().resolve()
                if (found := shutil.which(str(Path(directory) / "gms")))
            ),
            None,
        )
        if not executable:
            raise FileNotFoundError("gms")
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and "GMS Tools" in result.stdout:
            print("[OK] gms command is already available")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass

    print("[ERROR] gms command not found or not working")
    return False


def _preferred_python_command() -> str:
    """Return a usable Python command/path for the current environment."""
    candidates = [sys.executable, "python3", "python"]
    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    return "python"


def setup_powershell_function():
    """Set up PowerShell function for gms command."""
    # Find the gms.py script relative to this script's location
    script_dir = Path(__file__).parent
    gms_script = script_dir / "gms.py"

    if not gms_script.exists():
        print(f"[ERROR] {gms_script} not found")
        return False

    py_cmd = _preferred_python_command()
    # Create the PowerShell function (session-scoped)
    quoted_python = py_cmd.replace("'", "''")
    quoted_root = str(script_dir.parent).replace("'", "''")
    function_def = (
        f"function gms {{ $env:PYTHONPATH = '{quoted_root}'; & '{quoted_python}' -P -m gms_helpers.gms @args }}"
    )

    print("[SETUP] For agents: Use this PowerShell function definition:")
    print(f"   {function_def}")
    print("")
    print("[INFO] Agents should execute this in their PowerShell session before using gms commands.")
    print("   This creates a temporary function that works for the current session.")
    print("")

    # Test direct script execution as fallback
    print("[TEST] Testing direct script execution...")
    try:
        test_direct = subprocess.run(
            [py_cmd, "-P", "-m", "gms_helpers.gms", "--version"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONSAFEPATH": "1", "PYTHONPATH": str(script_dir.parent)},
        )

        if test_direct.returncode == 0 and "GMS Tools" in test_direct.stdout:
            print("[OK] Direct script execution works")
            print(f'   Agents can use: {py_cmd} "{gms_script}" [commands]')
            return True
        else:
            print("[ERROR] Direct script execution failed")
            return False

    except Exception as e:
        # Check if we're in a test environment to avoid confusing users with expected errors
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GMS_TEST_SUITE"):
            print(f"[EXPECTED ERROR] Error testing direct execution: {e}")
        else:
            print(f"[ERROR] Error testing direct execution: {e}")
        return False


def setup_bash_alias():
    """Set up bash/zsh alias for gms command."""
    # Find the gms.py script relative to this script's location
    script_dir = Path(__file__).parent
    gms_script = script_dir / "gms.py"

    if not gms_script.exists():
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GMS_TEST_SUITE"):
            print(f"[EXPECTED ERROR] {gms_script} not found")
        else:
            print(f"[ERROR] {gms_script} not found")
        return False

    py_cmd = _preferred_python_command()
    # Create the alias
    command = shlex.join(["env", f"PYTHONPATH={script_dir.parent}", py_cmd, "-P", "-m", "gms_helpers.gms"])
    alias_def = "alias gms=" + shlex.quote(command)

    print("[SETUP] Setting up bash alias...")
    print(f"   {alias_def}")

    print("[INFO] Run the alias definition above in your shell, or add it to ~/.bashrc or ~/.zshrc.")
    return True


def auto_setup():
    """Automatically set up gms command based on environment."""
    print("GMS Agent Auto-Setup")
    print("======================")

    # First check if already set up
    if test_gms_command():
        return True

    # Try automatic installation for persistent setup first
    try:
        subprocess.run(
            [sys.executable, "-P", "-m", "gms_helpers.install", "--auto"],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONSAFEPATH": "1", "PYTHONPATH": str(Path(__file__).resolve().parent.parent)},
        )
    except Exception:
        pass  # Ignore if auto install fails - we'll fall back to session-only function

    # Re-check after attempted auto-install
    if test_gms_command():
        return True

    # Detect shell and set up session function/alias accordingly
    shell = detect_shell()
    print(f"[INFO] Detected shell: {shell}")

    if shell == "powershell":
        return setup_powershell_function()
    else:
        return setup_bash_alias()


def main():
    """Main entry point."""
    success = auto_setup()

    if success:
        print("\n[OK] Setup complete! You can now use 'gms' commands.")
        print("\nExample usage:")
        print("  gms --help")
        print("  gms asset create script my_function --parent-path 'folders/Scripts.yy'")
        print("  gms maintenance auto")
    else:
        print("\n[ERROR] Setup failed. Please run manually:")
        print("  pipx install gms-mcp")

    return success


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        sys.exit(e.exit_code)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
