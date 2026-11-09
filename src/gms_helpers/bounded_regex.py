"""Regular-expression matching with a hard time limit for caller-supplied patterns.

Python's ``re`` engine backtracks, so a valid pattern such as ``(a+)+$`` can take exponential time.
Alternation backtracks too: ``(a|a)`` repeated twenty times explores a million paths per position
without a single quantifier. Patterns that contain repetition or alternation run in an isolated child
interpreter that is killed at the deadline; patterns with neither match in linear time and run in-process.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence

MAX_PATTERN_LENGTH = 1000
DEFAULT_TIMEOUT_SECONDS = 5.0

# Repetition or alternation, the two sources of backtracking (escaped characters included, conservatively).
_BACKTRACKING = re.compile(r"[*+?{|]")

_CHILD_SOURCE = """
import json, re, sys
request = json.load(sys.stdin)
prog = re.compile(request["pattern"], request["flags"])
limit = request["max_matches"]
found = []
for index, text in enumerate(request["texts"]):
    match = prog.search(text)
    if match:
        found.append([index, match.group(0)])
        if limit is not None and len(found) >= limit:
            break
json.dump(found, sys.stdout)
"""


class RegexTimeoutError(ValueError):
    """Raised when a pattern does not finish matching before the deadline."""


def compile_pattern(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """Validate a caller-supplied pattern; raises ``re.error`` or ``ValueError``."""
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"Regular expression is longer than {MAX_PATTERN_LENGTH} characters.")
    return re.compile(pattern, flags)


def search_many(
    pattern: str,
    texts: Sequence[str],
    *,
    flags: int = 0,
    max_matches: int | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[tuple[int, str]]:
    """Return ``(index, matched_text)`` for each text the pattern matches, in order.

    Stops after ``max_matches`` matches. Raises ``RegexTimeoutError`` when matching exceeds ``timeout``.
    """
    prog = compile_pattern(pattern, flags)
    if not _BACKTRACKING.search(pattern):
        found: list[tuple[int, str]] = []
        for index, text in enumerate(texts):
            match = prog.search(text)
            if match:
                found.append((index, match.group(0)))
                if max_matches is not None and len(found) >= max_matches:
                    break
        return found

    request = json.dumps({"pattern": pattern, "flags": flags, "max_matches": max_matches, "texts": list(texts)})
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _CHILD_SOURCE],
            input=request,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=tempfile.gettempdir(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RegexTimeoutError(
            f"Regular expression took longer than {timeout:g} seconds; simplify nested repetition such as (a+)+."
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Regular-expression worker failed: {completed.stderr.strip()[-500:]}")
    return [(int(index), str(text)) for index, text in json.loads(completed.stdout)]
