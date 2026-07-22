from __future__ import annotations

import argparse

from .telemetry import flush_spool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gms_mcp.telemetry_runtime")
    parser.add_argument("action", choices=["flush-spool"])
    args = parser.parse_args(argv)

    if args.action == "flush-spool":
        result = flush_spool(force=False)
        return 0 if result.ok else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
