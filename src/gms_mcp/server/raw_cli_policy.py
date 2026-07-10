"""Safety policy for the MCP wrapper around this project's ``gms`` helper CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


_READ_ONLY_COMMAND_PATHS = frozenset(
    {
        ("diagnostics",),
        ("event", "list"),
        ("event", "validate"),
        ("maintenance", "health"),
        ("maintenance", "list-orphans"),
        ("maintenance", "validate-json"),
        ("maintenance", "validate-paths"),
        ("room", "instance", "list"),
        ("room", "layer", "list"),
        ("room", "ops", "list"),
        ("sprite-frames", "count"),
        ("texture-groups", "list"),
        ("texture-groups", "members"),
        ("texture-groups", "show"),
    }
)
_META_ARGUMENTS = frozenset({"-h", "--help", "--version"})
_BLOCKED_GLOBAL_OPTIONS = ("--project-root", "--telemetry")


@dataclass(frozen=True)
class RawCLICommandDecision:
    """Classifies a requested raw helper-CLI invocation."""

    allowed: bool
    reason: str
    command_path: tuple[str, ...] = ()


def _is_blocked_global_option(token: str) -> bool:
    option_name = token.split("=", 1)[0]
    return option_name.startswith("--") and any(option.startswith(option_name) for option in _BLOCKED_GLOBAL_OPTIONS)


def evaluate_gm_cli_args(args: Any) -> RawCLICommandDecision:
    """Allow only explicit non-mutating ``gms`` command paths through ``gm_cli``."""
    if not isinstance(args, (list, tuple)) or not args:
        return RawCLICommandDecision(False, "args must be a non-empty list of non-empty strings.")
    if any(not isinstance(token, str) or not token.strip() for token in args):
        return RawCLICommandDecision(False, "args must be a non-empty list of non-empty strings.")

    normalized = tuple(args)
    if any(_is_blocked_global_option(token) for token in normalized):
        return RawCLICommandDecision(
            False,
            "Raw global CLI options are not permitted; pass the project root through gm_cli.project_root.",
        )

    # gms handles these before dispatching to a command handler, so they cannot perform a write.
    if any(token in _META_ARGUMENTS for token in normalized):
        return RawCLICommandDecision(True, "CLI help/version request.")

    for command_path in _READ_ONLY_COMMAND_PATHS:
        if normalized[: len(command_path)] == command_path:
            return RawCLICommandDecision(True, "Explicit read-only helper CLI command.", command_path)

    return RawCLICommandDecision(
        False,
        "The requested helper CLI command is not in the gm_cli read-only allowlist; use a named MCP tool.",
    )


def raw_cli_blocked_result(decision: RawCLICommandDecision) -> Dict[str, Any]:
    """Return the standard MCP payload for a raw helper-CLI policy denial."""
    return {
        "ok": False,
        "direct_used": False,
        "stdout": "",
        "stderr": "",
        "exit_code": None,
        "error": "Raw gms command is not permitted by the gm_cli read-only policy.",
        "blocked_by_policy": True,
        "policy": "gm_cli_read_only",
        "tool": "gm_cli",
        "reason": decision.reason,
        "fallback_skipped": True,
        "fallback_skipped_reason": "gm_cli_read_only",
        "execution_mode": "policy",
    }
