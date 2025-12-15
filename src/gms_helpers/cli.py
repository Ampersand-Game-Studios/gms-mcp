from __future__ import annotations


def main() -> None:
    from .gms import main as _main

    raise SystemExit(0 if _main() else 1)

