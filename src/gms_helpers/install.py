#!/usr/bin/env python3
"""
GMS Tools Installation Script
Creates convenient access to the gms command.
"""

import os
import sys
import platform
import shlex
import tempfile
from pathlib import Path
from typing import Any, cast
from .exceptions import GMSError


# Every launcher this module writes runs the CLI module; a file without it is someone else's.
LAUNCHER_MARKER = "-m gms_helpers.gms"


def _write_launcher(target: Path, content: str, mode: int = 0o755) -> None:
    """Write a launcher, replacing only a regular file this module wrote earlier.

    Never follows or replaces a symlink, and never overwrites a different program named gms.
    """
    if target.is_symlink():
        raise FileExistsError(f"{target} is a symlink; leaving it alone. Remove it to let gms-mcp install a launcher.")
    if target.exists():
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = ""
        if not target.is_file() or LAUNCHER_MARKER not in current:
            raise FileExistsError(
                f"{target} already exists and was not written by gms-mcp; leaving it alone. "
                "Remove or rename it to let gms-mcp install a launcher."
            )
    descriptor, temporary = tempfile.mkstemp(prefix=".gms-launcher-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        # os.replace swaps the directory entry itself, so a symlink created meanwhile is not followed.
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


# Added optional auto flag to trigger silent installation steps
def install_gms_command(auto: bool = False):
    """Install gms command for easy access."""
    script_dir = Path(__file__).parent
    cli_dir = script_dir.parent
    module_command = [sys.executable, "-P", "-m", "gms_helpers.gms"]
    quoted_python = sys.executable.replace("'", "''")
    quoted_root = str(cli_dir).replace("'", "''")

    is_windows = platform.system() == "Windows"

    if is_windows:
        print("[INFO] Windows detected")
        print("\nTo use the 'gms' command, you have several options:")
        print("\n1. Create an alias in PowerShell:")
        print(
            f"   function gms {{ $env:PYTHONPATH = '{quoted_root}'; & '{quoted_python}' -P -m gms_helpers.gms @args }}"
        )
        print("\n2. Use the full path:")
        print(f"   $env:PYTHONPATH = '{quoted_root}'; & '{quoted_python}' -P -m gms_helpers.gms [commands]")

        # Preferred approach on Windows: create a shim in WindowsApps (usually already on PATH)
        shim = None
        try:
            windows_apps = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
            if windows_apps.exists():
                if any(char in str(cli_dir) + sys.executable for char in '&|<>^%!"\r\n'):
                    raise ValueError("Unsafe characters in command shim path")
                shim_content = (
                    f'@echo off\r\nset "PYTHONPATH={cli_dir}"\r\n"{sys.executable}" -P -m gms_helpers.gms %*\r\n'
                )
                _write_launcher(windows_apps / "gms.cmd", shim_content)
                shim = windows_apps / "gms.cmd"
                print(f"\n[OK] Shim created at {shim}")
                print("   You can usually run: gms --help  (may require opening a new terminal)")
            else:
                print("\n[WARN] LOCALAPPDATA\\Microsoft\\WindowsApps not found; shim not created")
        except Exception as e:
            print(f"\n[WARN] Could not create WindowsApps shim: {e}")

        # The PATH entry must be the folder that holds the launcher; nothing else contains one.
        if shim is None:
            print("\n[INFO] No launcher was created, so there is no folder to add to PATH; use option 1 or 2.")
        elif auto:
            try:
                winreg = cast(Any, __import__("winreg"))

                def _normalize_path_list(path_value: str):
                    return [p.strip() for p in path_value.split(os.pathsep) if p.strip()]

                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as k:
                    try:
                        current_path, value_type = winreg.QueryValueEx(k, "Path")
                    except FileNotFoundError:
                        current_path, value_type = "", winreg.REG_EXPAND_SZ

                launcher_dir = str(shim.parent)
                paths = _normalize_path_list(current_path or "")
                if launcher_dir not in paths:
                    new_path = (current_path + os.pathsep if current_path else "") + launcher_dir
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE) as k:
                        winreg.SetValueEx(k, "Path", 0, value_type, new_path)
                    print(f"\n[OK] Added to user PATH (HKCU\\Environment\\Path): {launcher_dir}")
                    print("   Windows may require a new terminal session to pick this up.")
                else:
                    print(f"\n[OK] Already present in user PATH: {launcher_dir}")
            except Exception as e:
                print(f"\n[WARN] Could not update user PATH via registry: {e}")
        else:
            print("\n[INFO] Tip (optional): add the launcher folder to PATH for the current session:")
            print("   $env:Path += ';" + str(shim.parent).replace("'", "''") + "'")

    else:
        # Unix-like systems (Linux, macOS)
        print("[INFO] Unix-like system detected")

        # Try to install in user's local bin
        local_bin = Path.home() / ".local" / "bin"

        if local_bin.exists():
            # Create a symlink or script
            target = local_bin / "gms"

            # Create a shell script instead of symlink for better compatibility
            shell_script = (
                "#!/bin/sh\nexec " + shlex.join(["env", f"PYTHONPATH={cli_dir}", *module_command]) + ' "$@"\n'
            )

            try:
                _write_launcher(target, shell_script)
                print(f"[OK] Installed gms command to {target}")
                print(f"   Make sure {local_bin} is in your PATH")

                # Check if local_bin is in PATH
                path_dirs = os.environ.get("PATH", "").split(os.pathsep)
                if str(local_bin) not in path_dirs:
                    print(f"\n[WARN] Add this to your shell configuration:")
                    print('   export PATH="$PATH":' + shlex.quote(str(local_bin)))

                return True

            except Exception as e:
                print(f"[ERROR] Could not install to {local_bin}: {e}")

        # Fallback instructions
        print(f"\n[ERROR] Could not auto-install. Manual options:")
        print(f"\n1. Create an alias:")
        print("   alias gms=" + shlex.quote(shlex.join(["env", f"PYTHONPATH={cli_dir}", *module_command])))
        print("\n2. Install the package entry point, which puts gms on PATH:")
        print("   pipx install gms-mcp")

    print("\n[INFO] Usage examples:")
    print("   gms --help")
    print('   gms asset create script my_function --parent-path "folders/Scripts.yy"')
    print("   gms event add o_player create")
    print("   gms maintenance auto --fix")

    return True


def _parse_args_and_run():
    """Parse CLI args and invoke install."""
    import argparse

    parser = argparse.ArgumentParser(description="Install gms command for easy access.")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Attempt fully automatic installation without further user steps.",
    )

    args = parser.parse_args()

    success = install_gms_command(auto=args.auto)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        _parse_args_and_run()
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        sys.exit(e.exit_code)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
