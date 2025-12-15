#!/usr/bin/env python3
"""
Convenience entrypoint for setting up the `gms` command.

For releases, prefer `gms` and `gms-mcp-init` entrypoints.
"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Re-export the full implementation so `import agent_setup` behaves like the
# original module (some tests/importers expect helper functions to exist).
from gms_helpers.agent_setup import *  # type: ignore  # noqa: F403,E402
from gms_helpers.agent_setup import main as _main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(0 if _main() else 1)









