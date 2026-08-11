"""Run the dedicated official 2026-07-28 input-required fixture server."""

from __future__ import annotations

import sys
from pathlib import Path

TEST_PYTHON_ROOT = Path(__file__).resolve().parents[2] / "python"
sys.path.insert(0, str(TEST_PYTHON_ROOT))

from support.mcp_resolve_conformance import build_server


if __name__ == "__main__":
    build_server().run(
        "streamable-http",
        host="127.0.0.1",
        port=8766,
        streamable_http_path="/mcp",
        stateless_http=True,
    )
