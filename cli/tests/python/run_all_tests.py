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

# Fix Windows UTF-8 encoding issues
if sys.platform == "win32":
    # Set stdout/stderr to UTF-8 encoding
    import io
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    # Set console output encoding to UTF-8 for subprocess calls
    os.environ["PYTHONIOENCODING"] = "utf-8"

    # Try to set console codepage to UTF-8 (Windows 10+)
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)  # UTF-8 codepage
    except:
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

def run_test_file(test_file_path):
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

        # Run the test from gamemaker directory so CLI tools find the .yyp file
        # Use absolute path for the test file since we're changing working directory
        result = subprocess.run([
            python_exe, str(test_file_path.resolve())
        ], cwd=str(gamemaker_dir),
        capture_output=False, text=True,
        env=os.environ.copy())

        return result.returncode == 0, result.returncode
    except Exception as e:
        print(f"[ERROR] Error running {test_file_path.name}: {e}")
        return False, -1

def main():
    """Main test runner function"""
    print("GameMaker Project Test Suite Runner")
    print("=" * 60)

    # Show which Python we're using
    python_exe = find_python_executable()
    print(f"Using Python: {python_exe}")

    try:
        version_result = subprocess.run([python_exe, "--version"],
                                      capture_output=True, text=True)
        if version_result.returncode == 0:
            print(f"Version: {version_result.stdout.strip()}")
    except:
        pass

    print("=" * 60)

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
    total_tests = 0

    # Set test suite flag for clearer logs
    os.environ["GMS_TEST_SUITE"] = "1"

    for test_file in sorted(test_files):
        success, exit_code = run_test_file(test_file)
        results.append((test_file.name, success, exit_code))

    # Print summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for _, success, _ in results if success)
    failed = len(results) - passed

    for test_name, success, exit_code in results:
        status = "PASS" if success else f"FAIL (exit code: {exit_code})"
        print(f"{test_name:<30} {status}")

    print(f"\nOVERALL RESULTS:")
    print(f"   Passed: {passed}/{len(results)}")
    print(f"   Failed: {failed}/{len(results)}")

    if failed == 0:
        print("\nALL TESTS PASSED")
        return 0
    else:
        print(f"\n{failed} test file(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
