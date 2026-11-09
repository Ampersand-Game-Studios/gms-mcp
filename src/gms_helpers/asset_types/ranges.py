"""Numeric argument checks shared by asset constructors.

The MCP validator applies the same limits; enforcing them here keeps CLI and
direct Python callers from writing assets GameMaker cannot load.
"""

from __future__ import annotations

from typing import Any, Optional


def require_int(value: Any, field: str, minimum: int, maximum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
        raise ValueError(f"{field} must be {bound}")
    return value


def require_number(value: Any, field: str, minimum: float, maximum: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    if value != value or value < minimum or (maximum is not None and value > maximum):
        bound = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
        raise ValueError(f"{field} must be {bound}")
    return float(value)
