"""Runner command implementations."""

from pathlib import Path
from typing import Dict, Any, Union

from ..results import RunnerResult, structured_error
from ..runner import GameMakerRunner, detect_default_target_platform


def _dict_result_is_ok(result: Dict[str, Any]) -> bool:
    if result.get("ok") is False or result.get("success") is False:
        return False
    if "error" in result and "ok" not in result and "success" not in result:
        return False
    return True


def _normalize_runner_dict(result: Dict[str, Any], *, operation: str) -> Dict[str, Any]:
    normalized = dict(result)
    ok = _dict_result_is_ok(normalized)
    normalized.setdefault("ok", ok)
    normalized.setdefault("success", ok)
    if not ok and "error" in normalized and not isinstance(normalized["error"], dict):
        message = str(normalized["error"])
        normalized["error"] = structured_error(
            f"{operation}_failed",
            message,
            error_type="runner_error",
            details={"operation": operation},
        ).to_dict()
        normalized.setdefault("message", message)
    return normalized


def handle_runner_compile(args) -> RunnerResult:
    """Handle project compilation."""
    try:
        # Use current working directory if no project root specified
        if hasattr(args, "project_root") and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()

        print(f"[BUILD] Compiling GameMaker project in: {project_root}")

        runtime_version = getattr(args, "runtime_version", None)
        runner = GameMakerRunner(project_root, runtime_version=runtime_version)

        platform = getattr(args, "platform", None) or detect_default_target_platform()
        runtime = getattr(args, "runtime", "VM")

        success = runner.compile_project(platform, runtime)

        if success:
            print("[SUCCESS] Compilation completed successfully!")
            return RunnerResult(
                success=True,
                message="Compilation completed successfully",
                exit_code=0,
                data={
                    "infrastructure_attempt_count": runner.infrastructure_attempt_count,
                    "retried_infrastructure_failure": runner.retried_infrastructure_failure,
                },
            )
        else:
            failure_message = runner.last_failure_message or "Build validation failed!"
            print(f"[ERROR] {failure_message}")
            return RunnerResult(
                success=False,
                message=failure_message,
                error=structured_error(
                    "compile_failed",
                    failure_message,
                    error_type="runner_error",
                    details={"platform": platform, "runtime": runtime},
                ),
                exit_code=1,
                data={
                    "infrastructure_attempt_count": runner.infrastructure_attempt_count,
                    "retried_infrastructure_failure": runner.retried_infrastructure_failure,
                },
            )

    except Exception as e:
        message = f"Error during compilation: {e}"
        print(f"[ERROR] {message}")
        return RunnerResult(
            success=False,
            message=message,
            error=structured_error("compile_exception", str(e), error_type=type(e).__name__),
            exit_code=1,
        )


def handle_runner_run(args) -> Union[RunnerResult, Dict[str, Any]]:
    """
    Handle project execution.

    Returns:
        If background=False: bool (True if game exited successfully)
        If background=True: dict with session info (pid, run_id, etc.)
    """
    try:
        # Use current working directory if no project root specified
        if hasattr(args, "project_root") and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()

        print(f"[START] Running GameMaker project in: {project_root}")

        runtime_version = getattr(args, "runtime_version", None)
        runner = GameMakerRunner(project_root, runtime_version=runtime_version)

        platform = getattr(args, "platform", None) or detect_default_target_platform()
        runtime = getattr(args, "runtime", "VM")
        background = getattr(args, "background", False)
        output_location = getattr(args, "output_location", "temp")

        result = runner.run_project_direct(platform, runtime, background, output_location)

        if isinstance(result, bool):
            if result:
                return RunnerResult(success=True, message="Game run completed successfully", exit_code=0)
            return RunnerResult(
                success=False,
                message=runner.last_failure_message or "Game run failed",
                error=structured_error(
                    "run_failed",
                    runner.last_failure_message or "Game run failed",
                    error_type="runner_error",
                    details={"platform": platform, "runtime": runtime, "background": background},
                ),
                exit_code=1,
            )
        if isinstance(result, dict):
            return _normalize_runner_dict(result, operation="run")
        return result

    except Exception as e:
        message = f"Error during execution: {e}"
        print(f"[ERROR] {message}")
        if getattr(args, "background", False):
            return _normalize_runner_dict(
                {"ok": False, "error": str(e), "message": f"Failed to start game: {e}"},
                operation="run",
            )
        return RunnerResult(
            success=False,
            message=message,
            error=structured_error("run_exception", str(e), error_type=type(e).__name__),
            exit_code=1,
        )


def handle_runner_stop(args) -> Dict[str, Any]:
    """
    Handle stopping the running game.

    Uses persistent session tracking to find and stop the game,
    even if called from a different process or after restart.

    Returns:
        Dict with result of stop operation
    """
    try:
        # Use current working directory if no project root specified
        if hasattr(args, "project_root") and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()

        print(f"[STOP] Stopping GameMaker project in: {project_root}")

        runner = GameMakerRunner(project_root)
        result = runner.stop_game()

        # Print result message
        if result.get("ok"):
            print(f"[OK] {result.get('message', 'Game stopped')}")
        else:
            print(f"[WARN] {result.get('message', 'Failed to stop game')}")

        return _normalize_runner_dict(result, operation="stop")

    except Exception as e:
        message = f"Error stopping game: {e}"
        print(f"[ERROR] {message}")
        return _normalize_runner_dict({"ok": False, "error": str(e), "message": message}, operation="stop")


def handle_runner_status(args) -> Dict[str, Any]:
    """
    Check if game is currently running.

    Uses persistent session tracking to check status,
    even if called from a different process or after restart.

    Returns:
        Dict with session info and running status
    """
    try:
        # Use current working directory if no project root specified
        if hasattr(args, "project_root") and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()

        runner = GameMakerRunner(project_root)
        status = runner.get_game_status()

        # Print status message
        print(f"[STATUS] {status.get('message', 'Unknown status')}")

        if status.get("running"):
            print(f"   PID: {status.get('pid')}")
            print(f"   Run ID: {status.get('run_id')}")
            print(f"   Started: {status.get('started_at')}")

        return _normalize_runner_dict(status, operation="status")

    except Exception as e:
        message = f"Error checking status: {e}"
        print(f"[ERROR] {message}")
        return _normalize_runner_dict({"ok": False, "error": str(e), "message": message}, operation="status")
