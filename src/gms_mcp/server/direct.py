"""Process-isolated execution for typed helper handlers."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import contextvars
import inspect
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from ..telemetry import SUPPRESS_CLI_TELEMETRY_ENV_VAR
from .project import _resolve_project_directory
from .results import ToolRunResult


_DirectThreadResult = TypeVar("_DirectThreadResult")
_CANCEL_POLL_SECONDS = 0.2
# Set by the shielded runner; worker threads inherit it through the copied context.
_DIRECT_CANCELLATION: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "gms_mcp_direct_cancellation", default=None
)


async def _run_direct_thread_shielded(
    callable_to_run: Callable[..., _DirectThreadResult],
    *args: Any,
    **kwargs: Any,
) -> _DirectThreadResult:
    """Finish isolated worker management before propagating task cancellation.

    Cancellation terminates the worker's process tree, so a cancelled call never
    waits for a long-running child (such as a foreground game) to exit on its own.
    """
    cancellation_requested = threading.Event()
    token = _DIRECT_CANCELLATION.set(cancellation_requested)
    try:
        worker = asyncio.create_task(asyncio.to_thread(callable_to_run, *args, **kwargs))
    finally:
        _DIRECT_CANCELLATION.reset(token)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError as cancellation:
        cancellation_requested.set()
        try:
            await worker
        finally:
            raise cancellation


def _normalize_direct_result(result_value: Any, *, operation: str) -> Any:
    from gms_helpers.results import normalize_result

    if isinstance(result_value, (bool, dict, list)):
        return normalize_result(result_value, operation=operation).to_dict()
    return result_value


def _result_failure_message(result_value: Any) -> str | None:
    payload: Any = result_value
    if hasattr(payload, "to_dict") and callable(payload.to_dict):
        payload = payload.to_dict()

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or payload.get("message") or "Operation failed")
        if error:
            return str(error)
        if payload.get("message"):
            return str(payload["message"])
        return None

    if hasattr(result_value, "message"):
        return str(result_value.message)
    return None


def _module_name_from_source(source_path: Path) -> str | None:
    """Recover an importable module name when a top-level file ran as ``__main__``."""
    candidates: list[tuple[int, str]] = []
    for entry in sys.path:
        root = Path(entry or os.curdir).resolve()
        try:
            relative = source_path.relative_to(root).with_suffix("")
        except ValueError:
            continue
        parts = relative.parts
        if parts and all(part.isidentifier() for part in parts):
            candidates.append((len(parts), ".".join(parts)))
    return min(candidates, default=(0, ""))[1] or None


def _handler_reference(handler: Callable[[argparse.Namespace], Any]) -> tuple[str, str, Path | None]:
    module_name = str(getattr(handler, "__module__", ""))
    qualname = str(getattr(handler, "__qualname__", ""))
    source_file = inspect.getsourcefile(handler)
    if module_name == "__main__" and source_file:
        module_name = _module_name_from_source(Path(source_file).resolve()) or module_name
    if not module_name or not qualname or module_name == "__main__" or "<locals>" in qualname:
        raise TypeError("Direct handlers must be importable top-level callables")
    module_root: Path | None = None
    if source_file:
        source_path = Path(source_file).resolve()
        module_parts = module_name.split(".")
        parent_index = max(0, len(module_parts) - 1)
        if parent_index < len(source_path.parents):
            module_root = source_path.parents[parent_index]
    return module_name, qualname, module_root


def _request_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_request_value(item) for item in value]
    if isinstance(value, tuple):
        return [_request_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _request_value(item) for key, item in value.items()}
    return str(value)


def _worker_environment(module_root: Path | None) -> dict[str, str]:
    from gms_helpers.transactions import transaction_subprocess_environment

    environment = os.environ.copy()
    environment[SUPPRESS_CLI_TELEMETRY_ENV_VAR] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update(transaction_subprocess_environment())
    environment["PYTHONSAFEPATH"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys([str(Path(__file__).resolve().parents[2]), *([str(module_root)] if module_root else [])])
    )
    return environment


def _run_direct(
    handler: Callable[[argparse.Namespace], Any],
    args: argparse.Namespace,
    project_root: str | None,
    timeout_seconds: int | None = None,
    normalize_result: bool = True,
) -> ToolRunResult:
    """Run one typed handler in a disposable child process."""
    project_directory = _resolve_project_directory(project_root)
    module_name, qualname, module_root = _handler_reference(handler)
    request = {
        "handler_module": module_name,
        "handler_qualname": qualname,
        "args": _request_value(vars(args)),
        "project_root": str(project_directory),
    }
    started = time.monotonic()
    with contextlib.ExitStack() as resources:
        ownership_manifest_path = None
        command = [
            sys.executable,
            "-P",
            "-u",
            "-m",
            "gms_mcp.server.direct_worker",
        ]
        worker_environment = _worker_environment(module_root)
        if getattr(handler, "__name__", "") in {"handle_runner_compile", "handle_runner_run"}:
            from .macos_runner_timeout import MACOS_OWNERSHIP_MANIFEST_ENV

            temp_dir = resources.enter_context(tempfile.TemporaryDirectory(prefix="gms-mcp-direct-runner-"))
            ownership_manifest_path = Path(temp_dir) / "macos-runner-ownership.json"
            worker_environment[MACOS_OWNERSHIP_MANIFEST_ENV] = str(ownership_manifest_path)
        process = subprocess.Popen(
            command,
            cwd=project_directory,
            env=worker_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200) if os.name == "nt" else 0),
        )
        cancellation_requested = _DIRECT_CANCELLATION.get()
        deadline = started + timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
        request_bytes: bytes | None = json.dumps(request, ensure_ascii=False).encode("utf-8")
        stop_reason: str | None = None
        while True:
            wait_seconds = None if deadline is None else max(0.0, deadline - time.monotonic())
            if cancellation_requested is not None:
                wait_seconds = _CANCEL_POLL_SECONDS if wait_seconds is None else min(wait_seconds, _CANCEL_POLL_SECONDS)
            try:
                response, worker_stderr = process.communicate(request_bytes, timeout=wait_seconds)
                break
            except subprocess.TimeoutExpired:
                # communicate() may be retried, but input is only sent on the first call.
                request_bytes = None
                if cancellation_requested is not None and cancellation_requested.is_set():
                    stop_reason = "cancelled"
                elif deadline is not None and time.monotonic() >= deadline:
                    stop_reason = "timeout"
                else:
                    continue
            from .subprocess_runner import _terminate_process_tree
            from .macos_runner_timeout import cleanup_macos_ownership_manifest

            terminated = _terminate_process_tree(process)
            cleanup_macos_ownership_manifest(ownership_manifest_path)
            elapsed = time.monotonic() - started
            return ToolRunResult(
                ok=False,
                stdout="",
                stderr="",
                direct_used=True,
                exit_code=process.returncode,
                error=(
                    "Direct worker was cancelled"
                    if stop_reason == "cancelled"
                    else f"Direct worker timed out after {timeout_seconds} seconds"
                ),
                pid=process.pid,
                elapsed_seconds=elapsed,
                timed_out=stop_reason == "timeout",
                command=command,
                cwd=str(project_directory),
                execution_mode="direct:isolated",
                result={"terminated": terminated, "cancelled": stop_reason == "cancelled"},
            )

        elapsed = time.monotonic() - started
        if not response:
            from .macos_runner_timeout import cleanup_macos_ownership_manifest

            cleanup_macos_ownership_manifest(ownership_manifest_path)
            return ToolRunResult(
                ok=False,
                stdout="",
                stderr=worker_stderr.decode("utf-8", errors="replace"),
                direct_used=True,
                exit_code=process.returncode,
                error=f"Direct worker exited without a response (exit {process.returncode})",
                pid=process.pid,
                elapsed_seconds=elapsed,
                command=command,
                cwd=str(project_directory),
                execution_mode="direct:isolated",
            )

        try:
            payload = json.loads(response)
            if not isinstance(payload, dict):
                raise ValueError("expected an object")
        except (OSError, ValueError) as exc:
            from .macos_runner_timeout import cleanup_macos_ownership_manifest

            cleanup_macos_ownership_manifest(ownership_manifest_path)
            return ToolRunResult(
                ok=False,
                stdout="",
                stderr="",
                direct_used=True,
                exit_code=process.returncode,
                error=f"Direct worker returned an invalid response: {exc}",
                pid=process.pid,
                elapsed_seconds=elapsed,
                command=command,
                cwd=str(project_directory),
                execution_mode="direct:isolated",
            )

        if not bool(payload.get("ok")):
            from .macos_runner_timeout import cleanup_macos_ownership_manifest

            cleanup_macos_ownership_manifest(ownership_manifest_path)

    raw_result = payload.get("result")
    result_value = (
        _normalize_direct_result(raw_result, operation=getattr(handler, "__name__", "direct_helper"))
        if normalize_result
        else raw_result
    )
    ok = bool(payload.get("ok"))
    error_text = payload.get("error")
    if not ok and not error_text:
        error_text = _result_failure_message(result_value)
    return ToolRunResult(
        ok=ok,
        stdout=str(payload.get("stdout") or ""),
        stderr=str(payload.get("stderr") or "") + worker_stderr.decode("utf-8", errors="replace"),
        direct_used=True,
        exit_code=payload.get("exit_code") if payload.get("exit_code") is not None else process.returncode,
        error=str(error_text) if error_text else None,
        pid=process.pid,
        elapsed_seconds=elapsed,
        command=command,
        cwd=str(project_directory),
        execution_mode="direct:isolated",
        result=result_value,
    )
