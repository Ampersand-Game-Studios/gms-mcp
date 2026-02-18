#!/usr/bin/env python3
"""
GameMaker Project Test Runner
Runs all test suites for the CLI tools
"""

import subprocess
import sys
import os
from pathlib import Path
import shutil
from typing import Optional, Tuple

def _configure_windows_console() -> None:
    """Apply UTF-8 console settings for standalone Windows execution."""
    if sys.platform != "win32":
        return

    # Set stdout/stderr to UTF-8 encoding
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    # Set console output encoding to UTF-8 for subprocess calls
    os.environ["PYTHONIOENCODING"] = "utf-8"

    # Try to set console codepage to UTF-8 (Windows 10+)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)  # UTF-8 codepage
    except Exception:
        pass  # Ignore if this fails on older Windows versions

# Ensure the src directory is on PYTHONPATH for all child processes so that
# imports like `gms_helpers` are resolved regardless of the working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
current_pythonpath = os.environ.get("PYTHONPATH", "")
src_dir = PROJECT_ROOT / "src"
pythonpath_parts = [p for p in current_pythonpath.split(os.pathsep) if p]
to_add = []
for p in (PROJECT_ROOT, src_dir):
    if str(p) not in pythonpath_parts:
        to_add.append(str(p))
if to_add:
    os.environ["PYTHONPATH"] = os.pathsep.join([*to_add, current_pythonpath]) if current_pythonpath else os.pathsep.join(to_add)

MCP_REQUIRED_MODULES = ("mcp", "fastmcp")
MCP_DEPENDENT_TESTS = {
    "test_bridge_one_shot_enable.py",
    "test_mcp_integration_tools.py",
}

def find_python_executable():
    """Find the best Python executable to use"""
    # Try different Python executables in order of preference
    candidates = [
        sys.executable,  # Current Python interpreter
        "python",        # Standard command
        "python3",       # Linux/Mac standard
        "py",           # Windows launcher
    ]

    # Add common Windows system installs if on Windows
    if os.name == 'nt':
        candidates.extend([
            r"C:\Python311\python.exe",  # Common Windows install
            r"C:\Program Files\Python311\python.exe",  # System install
            r"C:\Python313\python.exe",  # Newer version
            r"C:\Program Files\Python313\python.exe",  # Newer system install
        ])

    # Check for environment override
    if 'PYTHON_EXEC_OVERRIDE' in os.environ:
        candidates.insert(1, os.environ['PYTHON_EXEC_OVERRIDE'])

    for candidate in candidates:
        if candidate == sys.executable:
            return candidate  # Always trust sys.executable

        # Check if command exists in PATH
        if shutil.which(candidate):
            return candidate

        # Check if it's a direct path that exists
        if os.path.exists(candidate):
            return candidate

    # Fallback to sys.executable
    return sys.executable


def _python_version_tuple(python_exe: str) -> Optional[Tuple[int, int, int]]:
    """Return interpreter version as (major, minor, patch), or None if unavailable."""
    try:
        result = subprocess.run(
            [python_exe, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split(".")
        if len(parts) != 3:
            return None
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return None


def _python_has_module(python_exe: str, module_name: str) -> bool:
    """Check whether module import succeeds for the provided interpreter."""
    try:
        result = subprocess.run(
            [python_exe, "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _determine_mcp_test_mode(python_exe: str) -> str:
    """
    Return one of:
      - "native": dependencies present in interpreter
      - "uv": run MCP tests through uv ephemeral deps
      - "skip": skip MCP tests with explicit reason
    """
    missing = [mod for mod in MCP_REQUIRED_MODULES if not _python_has_module(python_exe, mod)]
    if not missing:
        return "native"
    if shutil.which("uv"):
        return "uv"
    return "skip"

def _test_requires_pytest(test_file_path: Path) -> bool:
    """Best-effort detection for tests that need pytest collection/runtime."""
    try:
        content = test_file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    markers = ("import pytest", "from pytest", "@pytest.")
    return any(marker in content for marker in markers)

def _python_has_pytest(python_exe: str) -> bool:
    try:
        result = subprocess.run(
            [python_exe, "-c", "import pytest"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False

def _build_test_command(test_file_path: Path, python_exe: str):
    """Build the command used to execute a test file."""
    test_path = str(test_file_path.resolve())
    if not _test_requires_pytest(test_file_path):
        return [python_exe, test_path], "python"

    if _python_has_pytest(python_exe):
        return [python_exe, "-m", "pytest", test_path, "-q"], "pytest"

    uv_exe = shutil.which("uv")
    if uv_exe:
        return [uv_exe, "run", "--with", "pytest", "python", "-m", "pytest", test_path, "-q"], "uv+pytest"

    return None, "pytest-missing"

def run_test_file(test_file_path, *, mcp_test_mode: str):
    """Run a single test file and return results"""
    print(f"\n{'='*60}")
    print(f"[RUN] {test_file_path.name}")
    print(f"{'='*60}")

    python_exe = find_python_executable()

    try:
        # Ensure gamemaker directory exists (it's ignored by git but needed as a default context)
        gamemaker_dir = PROJECT_ROOT / "gamemaker"
        if not gamemaker_dir.exists():
            gamemaker_dir.mkdir(parents=True, exist_ok=True)
            # Create a minimal .yyp if it's completely missing
            yyp_file = gamemaker_dir / "minimal.yyp"
            if not any(gamemaker_dir.glob("*.yyp")):
                with open(yyp_file, "w") as f:
                    f.write('{"resources":[], "MetaData":{"name":"minimal"}}')

        test_name = test_file_path.name
        if test_name in MCP_DEPENDENT_TESTS:
            if mcp_test_mode == "skip":
                print("[SKIP] Missing MCP dependencies (mcp, fastmcp) and uv is unavailable.")
                return "skip", 0
            if mcp_test_mode == "uv":
                command = [
                    "uv",
                    "run",
                    "--with",
                    "mcp",
                    "--with",
                    "fastmcp",
                    "--with",
                    "pytest",
                    "python",
                    "-m",
                    "pytest",
                    str(test_file_path.resolve()),
                    "-q",
                ]
                mode = "uv+mcp-deps"
            else:
                command, mode = _build_test_command(test_file_path, python_exe)
        else:
            command, mode = _build_test_command(test_file_path, python_exe)
        if command is None:
            print(
                f"[ERROR] {test_file_path.name} requires pytest, but pytest is unavailable "
                "and uv is not installed."
            )
            return "fail", 1

        print(f"[MODE] {mode}")
        # Run from gamemaker directory so CLI tools find the .yyp file.
        result = subprocess.run(
            command,
            cwd=str(gamemaker_dir),
            capture_output=False,
            text=True,
            env=os.environ.copy(),
        )

        return ("pass" if result.returncode == 0 else "fail"), result.returncode
    except Exception as e:
        print(f"[ERROR] Error running {test_file_path.name}: {e}")
        return "fail", -1

def main():
    """Main test runner function"""
    _configure_windows_console()
    print("GameMaker Project Test Suite Runner")
    print("=" * 60)

    # Show which Python we're using
    python_exe = find_python_executable()
    print(f"Using Python: {python_exe}")

    try:
        version_result = subprocess.run([python_exe, "--version"], capture_output=True, text=True)
        if version_result.returncode == 0:
            version_text = (version_result.stdout or version_result.stderr).strip()
            print(f"Version: {version_text}")
    except Exception:
        pass

    print("=" * 60)

    py_ver = _python_version_tuple(python_exe)
    if py_ver is None:
        print("[ERROR] Could not determine Python interpreter version.")
        return 1
    if py_ver < (3, 10, 0):
        print(
            "[ERROR] Python 3.10+ is required by this project. "
            f"Detected {py_ver[0]}.{py_ver[1]}.{py_ver[2]} from '{python_exe}'."
        )
        print("[HINT] Use Python 3.12 for local development, e.g. `python3.12 cli/tests/python/run_all_tests.py`.")
        return 1

    mcp_test_mode = _determine_mcp_test_mode(python_exe)
    if mcp_test_mode == "uv":
        print("[INFO] MCP deps missing in interpreter; MCP-specific tests will run via uv with ephemeral deps.")
    elif mcp_test_mode == "skip":
        print("[WARN] MCP deps missing and uv unavailable; MCP-specific tests will be marked SKIP.")

    # Find all test files (relative to this script, not the caller's CWD)
    test_dir = Path(__file__).resolve().parent
    test_files = list(test_dir.glob("test_*.py"))

    if not test_files:
        print("[ERROR] No test files found in current directory")
        return 1

    print(f"Found {len(test_files)} test files:")
    for test_file in test_files:
        print(f"  - {test_file.name}")

    # Run all tests
    results = []

    # Set test suite flag for clearer logs
    os.environ["GMS_TEST_SUITE"] = "1"

    for test_file in sorted(test_files):
        status, exit_code = run_test_file(test_file, mcp_test_mode=mcp_test_mode)
        results.append((test_file.name, status, exit_code))

    # Print summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for _, status, _ in results if status == "pass")
    skipped = sum(1 for _, status, _ in results if status == "skip")
    failed = sum(1 for _, status, _ in results if status == "fail")

    for test_name, status, exit_code in results:
        if status == "pass":
            summary = "PASS"
        elif status == "skip":
            summary = "SKIP (missing dependency)"
        else:
            summary = f"FAIL (exit code: {exit_code})"
        print(f"{test_name:<30} {summary}")

    print(f"\nOVERALL RESULTS:")
    print(f"   Passed: {passed}/{len(results)}")
    print(f"   Skipped: {skipped}/{len(results)}")
    print(f"   Failed: {failed}/{len(results)}")

    if failed == 0:
        print("\nALL TESTS PASSED")
        return 0
    else:
        print(f"\n{failed} test file(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
