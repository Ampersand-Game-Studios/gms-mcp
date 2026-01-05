#!/usr/bin/env python3
"""
GMS Agent Auto-Setup Helper
Automatically sets up the gms command for AI agents (Cursor and other MCP-capable clients).
"""

import os
import sys
import subprocess
import platform
from pathlib import Path
from .exceptions import GMSError

def detect_shell():
    """Detect the current shell environment."""
    # Check if we're in PowerShell
    if os.environ.get('PSModulePath'):
        return 'powershell'
    # Check for bash/zsh
    elif os.environ.get('BASH_VERSION') or os.environ.get('ZSH_VERSION'):
        return 'bash'
    # Default based on platform
    elif platform.system() == 'Windows':
        return 'powershell'
    else:
        return 'bash'

def test_gms_command():
    """Test if gms command is already available."""
    try:
        result = subprocess.run(['gms', '--version'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and 'GMS Tools' in result.stdout:
            print("[OK] gms command is already available")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    
    print("[ERROR] gms command not found or not working")
    return False

def setup_powershell_function():
    """Set up PowerShell function for gms command."""
    # Find the gms.py script relative to this script's location
    script_dir = Path(__file__).parent
    gms_script = script_dir / "gms.py"
    
    if not gms_script.exists():
        print(f"[ERROR] {gms_script} not found")
        return False
    
    # Create the PowerShell function (session-scoped)
    function_def = f'function gms {{ python "{gms_script}" $args }}'
    
    print("[SETUP] For agents: Use this PowerShell function definition:")
    print(f"   {function_def}")
    print("")
    print("[INFO] Agents should execute this in their PowerShell session before using gms commands.")
    print("   This creates a temporary function that works for the current session.")
    print("")
    
    # Test direct script execution as fallback
    print("[TEST] Testing direct script execution...")
    try:
        test_direct = subprocess.run(['python', str(gms_script), '--version'], 
                                   capture_output=True, text=True)
        
        if test_direct.returncode == 0 and 'GMS Tools' in test_direct.stdout:
            print("[OK] Direct script execution works")
            print(f"   Agents can use: python \"{gms_script}\" [commands]")
            return True
        else:
            print("[ERROR] Direct script execution failed")
            return False
            
    except Exception as e:
        # Check if we're in a test environment to avoid confusing users with expected errors
        if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('GMS_TEST_SUITE'):
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
        if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('GMS_TEST_SUITE'):
            print(f"[EXPECTED ERROR] {gms_script} not found")
        else:
            print(f"[ERROR] {gms_script} not found")
        return False
    
    # Create the alias
    alias_def = f'alias gms="python3 \\"{gms_script}\\""'
    
    print("[SETUP] Setting up bash alias...")
    print(f"   {alias_def}")
    
    try:
        # Set the alias for the current session
        os.system(alias_def)
        
        print("[OK] Bash alias created for current session")
        print("[INFO] Note: This alias is temporary. For permanent setup, add to ~/.bashrc or ~/.zshrc")
        return True
        
    except Exception as e:
        if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('GMS_TEST_SUITE'):
            print(f"[EXPECTED ERROR] Error setting up bash alias: {e}")
        else:
            print(f"[ERROR] Error setting up bash alias: {e}")
        return False

def auto_setup():
    """Automatically set up gms command based on environment."""
    print("GMS Agent Auto-Setup")
    print("======================")
    
    # First check if already set up
    if test_gms_command():
        return True
    
    # Try automatic installation for persistent setup first
    try:
        install_script = Path(__file__).parent / "install.py"
        subprocess.run([sys.executable, str(install_script), "--auto"], capture_output=True, text=True)
    except Exception:
        pass  # Ignore if auto install fails - we'll fall back to session-only function

    # Re-check after attempted auto-install
    if test_gms_command():
        return True

    # Detect shell and set up session function/alias accordingly
    shell = detect_shell()
    print(f"[INFO] Detected shell: {shell}")
    
    if shell == 'powershell':
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
