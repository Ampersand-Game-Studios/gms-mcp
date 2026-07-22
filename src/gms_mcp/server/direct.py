"""Process-isolated execution for typed helper handlers."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from ..telemetry import SUPPRESS_CLI_TELEMETRY_ENV_VAR
from .project import _resolve_project_directory, _with_cli_pythonpath
from .results import ToolRunResult


_DirectThreadResult = TypeVar("_DirectThreadResult")


async def _run_direct_thread_shielded(
    callable_to_run: Callable[..., _DirectThreadResult],
    *args: Any,
    **kwargs: Any,
) -> _DirectThreadResult:
    """Finish isolated worker management before propagating task cancellation."""
    worker = asyncio.create_task(asyncio.to_thread(callable_to_run, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError as cancellation:
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

    environment = _with_cli_pythonpath(os.environ.copy())
    environment[SUPPRESS_CLI_TELEMETRY_ENV_VAR] = "1"
    environment.update(transaction_subprocess_environment())
    if module_root is not None:
        current = [part for part in environment.get("PYTHONPATH", "").split(os.pathsep) if part]
        root_value = str(module_root)
        if root_value not in current:
            environment["PYTHONPATH"] = os.pathsep.join([root_value, *current])
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
    with tempfile.TemporaryDirectory(prefix="gms-mcp-direct-") as temp_dir:
        request_path = Path(temp_dir) / "request.json"
        response_path = Path(temp_dir) / "response.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        command = [
            sys.executable,
            "-u",
            "-m",
            "gms_mcp.server.direct_worker",
            str(request_path),
            str(response_path),
        ]
        process = subprocess.Popen(
            command,
            cwd=project_directory,
            env=_worker_environment(module_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200) if os.name == "nt" else 0),
        )
        try:
            process.wait(timeout=timeout_seconds if timeout_seconds and timeout_seconds > 0 else None)
        except subprocess.TimeoutExpired:
            from .subprocess_runner import _terminate_process_tree

            terminated = _terminate_process_tree(process)
            elapsed = time.monotonic() - started
            return ToolRunResult(
                ok=False,
                stdout="",
                stderr="",
                direct_used=True,
                exit_code=process.returncode,
                error=f"Direct worker timed out after {timeout_seconds} seconds",
                pid=process.pid,
                elapsed_seconds=elapsed,
                timed_out=True,
                command=command,
                cwd=str(project_directory),
                execution_mode="direct:isolated",
                result={"terminated": terminated},
            )

        elapsed = time.monotonic() - started
        if not response_path.exists():
            return ToolRunResult(
                ok=False,
                stdout="",
                stderr="",
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
            payload = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
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
        stderr=str(payload.get("stderr") or ""),
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
