from __future__ import annotations

import sys


def _server_main() -> int:
    from .gamemaker_mcp_server import main as _main

    return int(_main() or 0)


def _init_main(argv: list[str] | None = None) -> int:
    from .install import main as _main

    return int(_main(argv) or 0)


def server() -> None:
    raise SystemExit(_server_main())


def init() -> None:
    raise SystemExit(_init_main())


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _server_main()
    if args[0] in {"-h", "--help"}:
        print("usage: gms-mcp [server|doctor|init] ...")
        print("Run bare `gms-mcp` with no arguments to start the MCP server.")
        return 0

    command, rest = args[0], args[1:]
    if command == "server":
        return _server_main()
    if command == "doctor":
        from .doctor import main as doctor_main

        return doctor_main(rest)
    if command == "init":
        return _init_main(rest)

    print(f"Unknown command: {command}", file=sys.stderr)
    print("Available commands: server, doctor, init", file=sys.stderr)
    print("Run bare `gms-mcp` with no arguments to start the MCP server.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
