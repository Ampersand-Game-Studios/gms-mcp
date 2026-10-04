from __future__ import annotations


def main() -> None:
    from .gms import main as _main
    from .exceptions import GMSError

    try:
        raise SystemExit(0 if _main() else 1)
    except GMSError as exc:
        raise SystemExit(exc.exit_code) from exc
