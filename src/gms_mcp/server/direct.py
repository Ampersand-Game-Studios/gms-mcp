from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from .project import _resolve_project_directory
from .results import ToolRunResult


@contextlib.contextmanager
def _pushd(target_directory: Path):
    """Temporarily change working directory."""
    previous_directory = Path.cwd()
    os.chdir(target_directory)
    try:
        yield
    finally:
        os.chdir(previous_directory)


def _capture_output(callable_to_run: Callable[[], Any]) -> Tuple[bool, str, str, Any, Optional[str], Optional[int]]:
    # ... buffers ...
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
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
                ok = result_value.success
            elif isinstance(result_value, bool):
                ok = result_value
            else:
                ok = True
        except GMSError as e:
            ok = False
            error_text = f"{type(e).__name__}: {e.message}"
            system_exit_code = e.exit_code
        except SystemExit as e:
            system_exit_code = getattr(e, "code", None)
            ok = system_exit_code in (0, None)
        except Exception:
            ok = False
            error_text = traceback.format_exc()

    try:
        stdout_buffer.flush()
        stderr_buffer.flush()
    except Exception:
        pass

    stdout_text = ""
    stderr_text = ""
    try:
        stdout_text = stdout_bytes.getvalue().decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.getvalue().decode("utf-8", errors="replace")
    except Exception:
        # Best-effort fallback
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


def _run_direct(handler: Callable[[argparse.Namespace], Any], args: argparse.Namespace, project_root: str | None) -> ToolRunResult:
    project_directory = _resolve_project_directory(project_root)

    def _invoke() -> Any:
        from gms_helpers.utils import validate_working_directory

        with _pushd(project_directory):
            # Mirror CLI behavior: validate and then run in the resolved directory.
            validate_working_directory()
            # Normalize project_root after chdir so downstream handlers behave consistently.
            setattr(args, "project_root", ".")
            return handler(args)

    ok, stdout_text, stderr_text, _result_value, error_text, exit_code = _capture_output(_invoke)
    return ToolRunResult(
        ok=ok,
        stdout=stdout_text,
        stderr=stderr_text,
        direct_used=True,
        exit_code=exit_code,
        error=error_text,
    )


def _run_gms_inprocess(cli_args: list[str], project_root: str | None) -> ToolRunResult:
    """
    Run `gms_helpers/gms.py` in-process (no subprocess), by importing it and calling `main()`.

    This avoids the class of hangs where a spawned Python process wedges (pip, PATH, antivirus, etc.).
    """
    project_root_value = project_root or "."

    def _invoke() -> bool:
        # Import the CLI entrypoint and run it as if invoked from command line.
        from gms_helpers import gms as gms_module

        previous_argv = sys.argv[:]
        try:
            sys.argv = ["gms", "--project-root", str(project_root_value), *cli_args]
            try:
                return bool(gms_module.main())
            except SystemExit as e:
                # argparse throws SystemExit on invalid args / help, etc.
                code = int(getattr(e, "code", 1) or 0)
                return code == 0
        finally:
            sys.argv = previous_argv

    ok, stdout_text, stderr_text, _result_value, error_text, exit_code = _capture_output(_invoke)
    return ToolRunResult(
        ok=ok,
        stdout=stdout_text,
        stderr=stderr_text,
        direct_used=True,
        exit_code=exit_code if exit_code is not None else (0 if ok else 1),
        error=error_text,
    )

