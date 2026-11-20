"""Progress reports for tool calls that build, run or wait their turn to do so."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

FIRST_REPORT_SECONDS = 10.0
REPORT_INTERVAL_SECONDS = 15.0
# A client that asked for progress and then stops reading must not be able to hold a tool call.
SEND_TIMEOUT_SECONDS = 2.0


def long_call_message(tool_name: str, elapsed_seconds: int, project_root: Path) -> str:
    """Say what a long call is doing, naming no host path or process."""
    from gms_helpers.gamemaker_machine_lock import machine_lock_holder

    message = f"{tool_name} has been running for {elapsed_seconds}s."
    holder = machine_lock_holder()
    if holder is None:
        return message
    operation = holder.get("operation") or "a build"
    held = holder.get("held_seconds")
    held_text = f" for {int(held)}s" if isinstance(held, (int, float)) else ""
    holder_root = holder.get("project_root")
    same_project = isinstance(holder_root, str) and os.path.normcase(holder_root) == os.path.normcase(str(project_root))
    if same_project:
        return f"{message} The machine's build turn is held by {operation} on this project{held_text}."
    return f"{message} Waiting for another project's {operation}, which has held the machine's build turn{held_text}."


async def _report(ctx: Any, tool_name: str, project_root: Path) -> None:
    started = time.monotonic()
    await asyncio.sleep(FIRST_REPORT_SECONDS)
    while True:
        elapsed = int(time.monotonic() - started)
        message = await asyncio.to_thread(long_call_message, tool_name, elapsed, project_root)
        try:
            await asyncio.wait_for(ctx.report_progress(elapsed, None, message), timeout=SEND_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - reporting is best effort and must never fail the tool call
            return
        await asyncio.sleep(REPORT_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def long_call_progress(ctx: Any, tool_name: str, project_root: Path) -> AsyncIterator[None]:
    """Report progress while the wrapped tool call runs.

    Nothing is sent unless the client asked for progress on this request (the SDK drops reports
    that have no progress token), the first report waits until the call is clearly a long one,
    and each send is bounded, so a client that stops reading cannot stall the call.
    """
    if ctx is None or not hasattr(ctx, "report_progress"):
        yield
        return
    reporter = asyncio.create_task(_report(ctx, tool_name, project_root))
    try:
        yield
    finally:
        reporter.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await reporter
