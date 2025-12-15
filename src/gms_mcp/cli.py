from __future__ import annotations


def server() -> None:
    from .gamemaker_mcp_server import main as _main

    raise SystemExit(int(_main() or 0))


def init() -> None:
    from .install import main as _main

    raise SystemExit(int(_main() or 0))

