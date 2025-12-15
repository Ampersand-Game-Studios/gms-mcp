#!/usr/bin/env python3
"""
Convenience entrypoint for generating workspace config(s) and installing helpers during development.

For releases, prefer the packaged entrypoints:
  - `gms-mcp-init` (generate MCP configs)
  - `gms` (CLI)
"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from gms_mcp.install import main as _main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_main())









