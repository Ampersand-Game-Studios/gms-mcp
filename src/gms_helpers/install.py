#!/usr/bin/env python3
"""
GMS Tools Installation Script
Creates convenient access to the gms command.
"""

import os
import sys
import platform
import subprocess
from pathlib import Path
from .exceptions import GMSError

# Added optional auto flag to trigger silent installation steps
def install_gms_command(auto: bool = False):
    """Install gms command for easy access."""
    script_dir = Path(__file__).parent
    cli_dir = script_dir.parent
    gms_py = script_dir / "gms.py"
    # Prefer the project-local wrapper so the CLI can be copied as a folder.
    gms_bat = cli_dir / "gms.bat"
    
    is_windows = platform.system() == "Windows"
    
    if is_windows:
        print("[INFO] Windows detected")
        print("\nTo use the 'gms' command, you have several options:")
        print("\n1. Add the CLI directory to your PATH:")
        print(f"   {cli_dir}")
        print("\n2. Create an alias in PowerShell:")
        print(f"   function gms {{ python \"{gms_py}\" $args }}")
        print("\n3. Use the full path:")
        print(f"   python \"{gms_py}\" [commands]")
        print("\n4. Use the batch file:")
        print(f"   \"{gms_bat}\" [commands]")
        
        # Preferred approach on Windows: create a shim in WindowsApps (usually already on PATH)
        shim_created = False
        try:
            windows_apps = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WindowsApps'
            if windows_apps.exists():
                shim = windows_apps / 'gms.cmd'
                shim_content = f"@echo off\r\n\"{sys.executable}\" \"{gms_py}\" %*\r\n"
                shim.write_text(shim_content, encoding="utf-8")
                print(f"\n[OK] Shim created at {shim}")
                print("   You can usually run: gms --help  (may require opening a new terminal)")
                shim_created = True
            else:
                print("\n[WARN] LOCALAPPDATA\\Microsoft\\WindowsApps not found; shim not created")
        except Exception as e:
            print(f"\n[WARN] Could not create WindowsApps shim: {e}")

        # Optional: add helper directory to *user* PATH safely (avoid setx PATH hazards)
        if auto:
            try:
                import winreg

                def _normalize_path_list(path_value: str):
                    return [p.strip() for p in path_value.split(os.pathsep) if p.strip()]

                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as k:
                    try:
                        current_path, value_type = winreg.QueryValueEx(k, "Path")
                    except FileNotFoundError:
                        current_path, value_type = "", winreg.REG_EXPAND_SZ

                paths = _normalize_path_list(current_path or "")
                if str(script_dir) not in paths:
                    new_path = (current_path + os.pathsep if current_path else "") + str(script_dir)
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE) as k:
                        winreg.SetValueEx(k, "Path", 0, value_type, new_path)
                    print(f"\n[OK] Added to user PATH (HKCU\\Environment\\Path): {script_dir}")
                    print("   Windows may require a new terminal session to pick this up.")
                else:
                    print(f"\n[OK] Already present in user PATH: {script_dir}")
            except Exception as e:
                print(f"\n[WARN] Could not update user PATH via registry: {e}")
        else:
            print("\n[INFO] Tip (optional): add this line to your PowerShell profile for the current session:")
            print(f"   $env:Path += \";{script_dir}\"")
    
    else:
        # Unix-like systems (Linux, macOS)
        print("[INFO] Unix-like system detected")
        
        # Try to install in user's local bin
        local_bin = Path.home() / ".local" / "bin"
        
        if local_bin.exists():
            # Create a symlink or script
            target = local_bin / "gms"
            
            # Create a shell script instead of symlink for better compatibility
            shell_script = f"""#!/bin/sh
python3 "{gms_py}" "$@"
"""
            
            try:
                target.write_text(shell_script)
                target.chmod(0o755)
                print(f"[OK] Installed gms command to {target}")
                print(f"   Make sure {local_bin} is in your PATH")
                
                # Check if local_bin is in PATH
                path_dirs = os.environ.get('PATH', '').split(os.pathsep)
                if str(local_bin) not in path_dirs:
                    print(f"\n[WARN] Add this to your shell configuration:")
                    print(f"   export PATH=\"$PATH:{local_bin}\"")
                    
                return True
                
            except Exception as e:
                print(f"[ERROR] Could not install to {local_bin}: {e}")
        
        # Fallback instructions
        print(f"\n[ERROR] Could not auto-install. Manual options:")
        print(f"\n1. Add this directory to your PATH:")
        print(f"   export PATH=\"$PATH:{script_dir}\"")
        print(f"\n2. Create an alias:")
        print(f"   alias gms='python3 \"{gms_py}\"'")
        print(f"\n3. Create a symlink:")
        print(f"   sudo ln -s \"{gms_py}\" /usr/local/bin/gms")
    
    print("\n[INFO] Usage examples:")
    print("   gms --help")
    print("   gms asset create script my_function --parent-path \"folders/Scripts.yy\"")
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
 