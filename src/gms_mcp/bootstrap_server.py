#!/usr/bin/env python3
"""
Bootstrap runner for the GameMaker MCP server.

This script is intended to be referenced from an MCP client's config.

In the packaged (pip) install flow, dependencies should already be installed.
So this script intentionally does not attempt to run pip automatically.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from .gamemaker_mcp_server import main as server_main
        return int(server_main() or 0)
    except ModuleNotFoundError as e:
        sys.stderr.write(
            "Missing dependency while starting the GameMaker MCP server.\n"
            "If you installed via pipx/pip, reinstall/upgrade:\n"
            "  pipx install gms-mcp-tools --force\n"
            "  # or\n"
            f"  {sys.executable} -m pip install -U gms-mcp-tools\n"
            f"\nDetails: {e}\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
