from __future__ import annotations

import argparse
from typing import Any, Callable, Dict, List

from ..telemetry import note_tool_execution
from ..execution_policy import ExecutionMode, policy_manager
from .destructive_policy import destructive_cli_blocked_result, is_real_destructive_cli_workflow
from .direct import _run_direct
from .output import _apply_output_mode
from .subprocess_runner import _run_cli_async


_DIRECT_DOMAIN_FAILURE_EXIT_CODES = {2, 3, 4, 5, 6, 9}
_DIRECT_DOMAIN_FAILURE_PREFIXES = (
    "AssetExistsError:",
    "AssetNotFoundError:",
    "InvalidAssetTypeError:",
    "JSONParseError:",
    "ProjectNotFoundError:",
    "ValidationError:",
)


def _is_structured_domain_failure(value: Any) -> bool:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, dict):
        return False
    if value.get("ok") is not False and value.get("success") is not False:
        return False
    error = value.get("error")
    if isinstance(error, dict):
        error_type = str(error.get("type") or "")
        code = str(error.get("code") or "")
        return bool(error_type or code)
    return bool(error)


def _should_skip_cli_fallback_for_direct_failure(direct_result: Any) -> bool:
    if direct_result.exit_code in _DIRECT_DOMAIN_FAILURE_EXIT_CODES:
        return True
    error = str(direct_result.error or "")
    if error.startswith(_DIRECT_DOMAIN_FAILURE_PREFIXES):
        return True
    return _is_structured_domain_failure(direct_result.result)


async def _run_with_fallback(
    *,
    direct_handler: Callable[[argparse.Namespace], Any],
    direct_args: argparse.Namespace,
    cli_args: List[str],
    project_root: str | None,
    prefer_cli: bool,
    output_mode: str = "full",
    tail_lines: int = 120,
    max_chars: int = 40000,
    quiet: bool = False,
    timeout_seconds: int | None = None,
    tool_name: str | None = None,
    ctx: Any | None = None,
) -> Dict[str, Any]:
    derived_tool_name = tool_name
    if not derived_tool_name:
        # Derive a stable tool identifier from the CLI args.
        # We intentionally ignore flags/values so policies like "run-compile"
        # keep applying even when the CLI invocation includes options.
        head: List[str] = []
        for token in cli_args or []:
            if not token:
                continue
            if token.startswith("-"):
                break
            head.append(token)
            if len(head) >= 3:
                break
        derived_tool_name = "-".join(head) if head else "tool"

    # Get execution policy for this tool
    policy = policy_manager.get_policy(derived_tool_name)
    effective_mode = policy.mode
    effective_timeout = timeout_seconds if timeout_seconds is not None else policy.timeout_seconds
    destructive_cli_disabled = is_real_destructive_cli_workflow(derived_tool_name, direct_args)

    # Respect manual override via prefer_cli
    if prefer_cli:
        effective_mode = ExecutionMode.SUBPROCESS

    if destructive_cli_disabled and prefer_cli:
        result = destructive_cli_blocked_result(
            derived_tool_name,
            "This MCP tool call would perform a real destructive write; use the typed direct handler instead.",
        )
        result = _apply_output_mode(
            result,
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )
        note_tool_execution(
            tool_name=derived_tool_name,
            execution_mode=result.get("execution_mode") or "policy",
            ok=bool(result.get("ok")),
            timed_out=bool(result.get("timed_out")),
            error=result.get("error"),
        )
        return result
    if destructive_cli_disabled:
        effective_mode = ExecutionMode.DIRECT

    if effective_mode == ExecutionMode.SUBPROCESS:
        result = _apply_output_mode(
            (
                await _run_cli_async(
                    cli_args,
                    project_root,
                    timeout_seconds=effective_timeout,
                    tool_name=derived_tool_name,
                    ctx=ctx,
                )
            ).as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )
        note_tool_execution(
            tool_name=derived_tool_name,
            execution_mode=result.get("execution_mode") or "subprocess",
            ok=bool(result.get("ok")),
            timed_out=bool(result.get("timed_out")),
            error=result.get("error"),
        )
        return result

    # ExecutionMode.DIRECT
    _ = ctx

    direct_result = _run_direct(direct_handler, direct_args, project_root)
    if direct_result.ok:
        result = _apply_output_mode(
            direct_result.as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )
        note_tool_execution(
            tool_name=derived_tool_name,
            execution_mode=result.get("execution_mode") or "direct",
            ok=bool(result.get("ok")),
            timed_out=bool(result.get("timed_out")),
            error=result.get("error"),
        )
        return result

    if _should_skip_cli_fallback_for_direct_failure(direct_result):
        result = _apply_output_mode(
            direct_result.as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )
        result["fallback_skipped"] = True
        result["fallback_skipped_reason"] = "direct_domain_failure"
        note_tool_execution(
            tool_name=derived_tool_name,
            execution_mode=result.get("execution_mode") or "direct",
            ok=bool(result.get("ok")),
            timed_out=bool(result.get("timed_out")),
            error=result.get("error"),
        )
        return result

    if destructive_cli_disabled:
        result = _apply_output_mode(
            direct_result.as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )
        result["fallback_skipped"] = True
        result["fallback_skipped_reason"] = "destructive_cli_disabled"
        result["fallback_blocked_by_policy"] = True
        note_tool_execution(
            tool_name=derived_tool_name,
            execution_mode=result.get("execution_mode") or "direct",
            ok=bool(result.get("ok")),
            timed_out=bool(result.get("timed_out")),
            error=result.get("error"),
        )
        return result

    # If the direct call failed for an infrastructure reason, fall back to subprocess for resilience.
    cli_result = await _run_cli_async(
        cli_args,
        project_root,
        timeout_seconds=timeout_seconds,
        tool_name=derived_tool_name,
        ctx=ctx,
    )
    cli_result.direct_error = direct_result.error or "Direct call failed"
    result = _apply_output_mode(
        cli_result.as_dict(),
        output_mode=output_mode,
        tail_lines=tail_lines,
        max_chars=max_chars,
        quiet=quiet,
    )
    note_tool_execution(
        tool_name=derived_tool_name,
        execution_mode=result.get("execution_mode") or "subprocess",
        ok=bool(result.get("ok")),
        timed_out=bool(result.get("timed_out")),
        error=result.get("error") or result.get("direct_error"),
    )
    return result
