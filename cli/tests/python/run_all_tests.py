#!/usr/bin/env python3
"""Run the complete suite with the project interpreter and pytest collection."""

from importlib.util import find_spec
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    missing = [name for name in ("pytest", "mcp") if find_spec(name) is None]
    if missing:
        print(f"[ERROR] Missing test dependencies: {', '.join(missing)}. Run uv sync --frozen --all-extras.")
        return 1
    test_root = PROJECT_ROOT / "cli/tests/python"
    if not list(test_root.glob("test_*.py")):
        print("[ERROR] No test suites found.")
        return 1
    env = dict(os.environ)
    env["GMS_TEST_SUITE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)])
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(test_root), "-q"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
