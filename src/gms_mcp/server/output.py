from __future__ import annotations

from typing import Any, Dict, Tuple


def _apply_output_mode(
    result: Dict[str, Any],
    *,
    output_mode: str = "full",
    tail_lines: int = 120,
    max_chars: int = 40000,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Pure output-shaping helper (no side effects, no command execution).
    """
    normalized_mode = output_mode
    if quiet and output_mode == "full":
        normalized_mode = "tail"

    def _tail(text: str) -> Tuple[str, bool]:
        if not text:
            return "", False
        lines = text.splitlines()
        if tail_lines > 0 and len(lines) > tail_lines:
            lines = lines[-tail_lines:]
        out = "\n".join(lines)
        if max_chars > 0 and len(out) > max_chars:
            out = out[-max_chars:]
            return out, True
        return out, False

    if normalized_mode not in ("full", "tail", "none"):
        normalized_mode = "tail"

    stdout_text = str(result.get("stdout", "") or "")
    stderr_text = str(result.get("stderr", "") or "")

    if normalized_mode == "full":
        return result
    if normalized_mode == "none":
        result["stdout"] = ""
        result["stderr"] = ""
        result["stdout_truncated"] = bool(stdout_text)
        result["stderr_truncated"] = bool(stderr_text)
        return result

    stdout_tail, stdout_truncated = _tail(stdout_text)
    stderr_tail, stderr_truncated = _tail(stderr_text)
    result["stdout"] = stdout_tail
    result["stderr"] = stderr_tail
    result["stdout_truncated"] = stdout_truncated or (tail_lines > 0 and len(stdout_text.splitlines()) > tail_lines)
    result["stderr_truncated"] = stderr_truncated or (tail_lines > 0 and len(stderr_text.splitlines()) > tail_lines)
    return result

