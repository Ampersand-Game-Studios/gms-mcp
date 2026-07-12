"""Single-call worker for process-isolated typed helper execution."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, Tuple


DIRECT_CAPTURE_MAX_BYTES = 1024 * 1024


class _CappedBytesIO(io.BytesIO):
    """Act like a writable byte stream while retaining only a fixed prefix."""

    def __init__(self, limit: int):
        super().__init__()
        self.limit = max(0, limit)
        self.omitted_bytes = 0

    def write(self, value: bytes) -> int:
        total = len(value)
        remaining = max(0, self.limit - self.tell())
        retained = min(total, remaining)
        if retained:
            super().write(value[:retained])
        self.omitted_bytes += total - retained
        return total


def _captured_text(buffer: _CappedBytesIO) -> str:
    text = buffer.getvalue().decode("utf-8", errors="replace")
    if buffer.omitted_bytes:
        text += f"\n[output truncated: {buffer.omitted_bytes} bytes omitted]\n"
    return text


@contextlib.contextmanager
def _pushd(target_directory: Path):
    """Change cwd inside this disposable single-call worker process."""
    previous_directory = Path.cwd()
    os.chdir(target_directory)
    try:
        yield
    finally:
        os.chdir(previous_directory)


def _capture_output(callable_to_run: Callable[[], Any]) -> Tuple[bool, str, str, Any, Optional[str], Optional[int]]:
    """Capture one worker call without exposing streams to the MCP server process."""
    stdout_bytes = _CappedBytesIO(DIRECT_CAPTURE_MAX_BYTES)
    stderr_bytes = _CappedBytesIO(DIRECT_CAPTURE_MAX_BYTES)
    stdout_buffer = io.TextIOWrapper(stdout_bytes, encoding="utf-8", errors="replace", line_buffering=True)
    stderr_buffer = io.TextIOWrapper(stderr_bytes, encoding="utf-8", errors="replace", line_buffering=True)
    result_value: Any = None
    error_text: Optional[str] = None
    system_exit_code: Any | None = None

    from gms_helpers.exceptions import GMSError

    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        try:
            result_value = callable_to_run()
            if hasattr(result_value, "success"):
                ok = bool(result_value.success)
            elif isinstance(result_value, bool):
                ok = result_value
            elif isinstance(result_value, dict):
                from gms_helpers.results import result_dict_is_ok

                ok = result_dict_is_ok(result_value)
            else:
                ok = True
        except GMSError as exc:
            ok = False
            error_text = f"{type(exc).__name__}: {exc.message}"
            system_exit_code = exc.exit_code
        except SystemExit as exc:
            system_exit_code = getattr(exc, "code", None)
            ok = system_exit_code in (0, None)
        except Exception:
            ok = False
            error_text = traceback.format_exc()

    try:
        stdout_buffer.flush()
        stderr_buffer.flush()
    except Exception:
        pass

    try:
        stdout_text = _captured_text(stdout_bytes)
        stderr_text = _captured_text(stderr_bytes)
    except Exception:
        stdout_text = ""
        stderr_text = ""

    if system_exit_code is not None and not ok and not error_text:
        pieces = [f"SystemExit: {system_exit_code!r}"]
        if stdout_text:
            pieces.append("stdout:\n" + stdout_text)
        if stderr_text:
            pieces.append("stderr:\n" + stderr_text)
        error_text = "\n".join(pieces)

    return ok, stdout_text, stderr_text, result_value, error_text, system_exit_code


def _resolve_handler(module_name: str, qualname: str) -> Callable[[argparse.Namespace], Any]:
    value: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        value = getattr(value, part)
    if not callable(value):
        raise TypeError(f"Direct handler is not callable: {module_name}.{qualname}")
    return value


def _jsonable_result(value: Any) -> Any:
    from .results import _jsonable_result as convert

    return convert(value)


def _run_request(request: dict[str, Any]) -> dict[str, Any]:
    project_directory = Path(str(request["project_root"])).resolve()
    handler = _resolve_handler(str(request["handler_module"]), str(request["handler_qualname"]))
    args_value = request.get("args")
    if not isinstance(args_value, dict):
        raise TypeError("Direct worker args must be an object")
    args = argparse.Namespace(**args_value)

    def invoke() -> Any:
        from gms_helpers.utils import validate_working_directory

        with _pushd(project_directory):
            validate_working_directory()
            setattr(args, "project_root", ".")
            return handler(args)

    from gms_helpers.transactions import inherited_transaction_context

    with inherited_transaction_context():
        ok, stdout, stderr, result, error, exit_code = _capture_output(invoke)
    return {
        "ok": ok,
        "stdout": stdout,
        "stderr": stderr,
        "result": _jsonable_result(result),
        "error": error,
        "exit_code": exit_code,
    }


def _write_response(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("request_path")
    parser.add_argument("response_path")
    options = parser.parse_args(argv)
    response_path = Path(options.response_path)
    try:
        request = json.loads(Path(options.request_path).read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise TypeError("Direct worker request must be an object")
        payload = _run_request(request)
    except Exception:
        payload = {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "result": None,
            "error": traceback.format_exc(),
            "exit_code": 1,
        }
    try:
        _write_response(response_path, payload)
        return 0
    except Exception:
        fallback = {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "result": None,
            "error": traceback.format_exc(),
            "exit_code": 1,
        }
        _write_response(response_path, fallback)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
