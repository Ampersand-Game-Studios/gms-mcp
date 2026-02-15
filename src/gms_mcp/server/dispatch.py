from __future__ import annotations

import argparse
from typing import Any, Callable, Dict, List

from ..execution_policy import ExecutionMode, policy_manager
from .direct import _run_direct
from .output import _apply_output_mode
from .subprocess_runner import _run_cli_async


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
        for token in (cli_args or []):
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

    # Respect manual override via prefer_cli
    if prefer_cli:
        effective_mode = ExecutionMode.SUBPROCESS

    if effective_mode == ExecutionMode.SUBPROCESS:
        return _apply_output_mode(
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

    # ExecutionMode.DIRECT
    _ = ctx

    direct_result = _run_direct(direct_handler, direct_args, project_root)
    if direct_result.ok:
        return _apply_output_mode(
            direct_result.as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )

    # If the direct call threw (or otherwise failed), fall back to subprocess for resilience.
    cli_result = await _run_cli_async(
        cli_args,
        project_root,
        timeout_seconds=timeout_seconds,
        tool_name=derived_tool_name,
        ctx=ctx,
    )
    cli_result.direct_error = direct_result.error or "Direct call failed"
    return _apply_output_mode(
        cli_result.as_dict(),
        output_mode=output_mode,
        tail_lines=tail_lines,
        max_chars=max_chars,
        quiet=quiet,
    )

