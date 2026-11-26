from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict

from .. import background_runs
from ..direct import _run_direct, _run_direct_thread_shielded
from ..dispatch import _run_with_fallback
from ..output import _apply_output_mode
from ..mcp_types import Context
from ..platform import _default_target_platform
from ..project import _ensure_cli_on_sys_path, _resolve_project_directory, _resolve_repo_root
from ..subprocess_runner import _default_timeout_seconds_for_cli_args
from ..tool_types import OutputMode, RunnerPlatform


def handle_runner_run(args: argparse.Namespace) -> Any:
    """Set bridge credentials only inside the disposable launch worker."""
    from gms_helpers.commands.runner_commands import handle_runner_run as run

    for key in ("GMS_MCP_BRIDGE_PORT", "GMS_MCP_BRIDGE_TOKEN"):
        os.environ.pop(key, None)
    environment = getattr(args, "bridge_environment", {})
    os.environ.update(environment)
    try:
        from gms_helpers.live_session import bridge_launch_environment

        with bridge_launch_environment(environment):
            return run(args)
    finally:
        for key in ("GMS_MCP_BRIDGE_PORT", "GMS_MCP_BRIDGE_TOKEN"):
            os.environ.pop(key, None)


# The label a working-tree compile is filed under for gm_build_status and gm_build_stop.
WORKING_TREE_LABEL = "working_tree"


def register(
    mcp: Any,
    ContextType: Any,
    *,
    read_only: bool = False,
    mutation_scope: Callable[[], Any] | None = None,
) -> None:
    """``mutation_scope`` is the server's lock on changes to the project, held for a whole working-tree compile."""
    globals()["Context"] = ContextType
    mutating_tool = (lambda function: function) if read_only else mcp.tool()

    def _run_direct_preserve_result(
        handler: Any,
        args: argparse.Namespace,
        project_root: str,
        timeout_seconds: int,
    ) -> tuple[bool, str, str, Any, str | None, int | None]:
        """Run a typed runner handler in the same isolated worker used by other tools."""
        result = _run_direct(
            handler,
            args,
            project_root,
            timeout_seconds=timeout_seconds,
            normalize_result=False,
        )
        return result.ok, result.stdout, result.stderr, result.result, result.error, result.exit_code

    # -----------------------------
    # Runner tools
    # -----------------------------
    @mutating_tool
    async def gm_compile(
        platform: RunnerPlatform | None = None,
        runtime: str = "VM",
        runtime_version: str | None = None,
        background: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Compile the project in its working tree to check that it builds, without running it.

        Returns the compiler output and any errors. Builds take turns across every session on
        this machine (gm_lock_status shows whose turn it is), and tools that change the project
        wait until it ends. gm_snapshot_compile checks the same on a copy, shows its log while
        it runs, and holds up nothing.
        Takes minutes: after about 20 s it returns STILL_RUNNING and carries on; follow it with
        gm_build_status(label="working_tree") or end it with gm_build_stop(label="working_tree").
        background=true returns at once.
        """
        selected_platform = platform or _default_target_platform()
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_compile

        args = argparse.Namespace(
            platform=selected_platform,
            runtime=runtime,
            runtime_version=runtime_version,
            project_root=project_root,
        )
        cli_args = ["run", "compile", "--platform", selected_platform, "--runtime", runtime]
        if runtime_version:
            cli_args.extend(["--runtime-version", runtime_version])

        _ = ctx  # The compile can outlive this request, so it is never handed the request's context.
        from gms_helpers import run_status
        from gms_helpers.snapshot_build import label_pipeline, runs_directory

        root = _resolve_project_directory(project_root)
        loop = asyncio.get_running_loop()
        pending: list[concurrent.futures.Future] = []
        began = threading.Event()
        unwound = threading.Event()

        async def compile_holding_the_project() -> Dict[str, Any]:
            began.set()
            try:
                return await compile_serialized()
            finally:
                # Set only once a cancelled compile has finished ending its compiler processes.
                unwound.set()

        async def compile_serialized() -> Dict[str, Any]:
            async def compile_now() -> Dict[str, Any]:
                run_status.report_stage("compiling")
                # The compiler runs in a child process and may write its output to a file of its own.
                # The child names that file here, in a folder only this server can write to.
                hint_directory = tempfile.mkdtemp(prefix="gms-mcp-live-log-")
                hint = Path(hint_directory) / "live_log.json"

                async def follow_compiler_log() -> None:
                    shown = None
                    while True:
                        await asyncio.sleep(0.5)
                        live_log = run_status.read_live_log_hint(hint)
                        if live_log is not None and live_log != shown:
                            shown = live_log
                            run_status.report_detail(live_log=live_log)

                follower = asyncio.create_task(follow_compiler_log())
                try:
                    result = await _run_with_fallback(
                        direct_handler=handle_runner_compile,
                        direct_args=args,
                        cli_args=cli_args,
                        project_root=project_root,
                        prefer_cli=prefer_cli,
                        output_mode=output_mode,
                        tail_lines=tail_lines,
                        quiet=quiet,
                        ctx=None,
                        extra_environment={run_status.LIVE_LOG_HINT_ENV: str(hint)},
                    )
                finally:
                    follower.cancel()
                    shutil.rmtree(hint_directory, ignore_errors=True)
                compiled = result
                if isinstance(result, dict) and "status" not in result:
                    # The same word a snapshot build gives, so a caller reads one field for either.
                    result = {**result, "status": "COMPILE_OK" if result.get("ok") else "BUILD_FAILED"}
                if isinstance(result, dict) and isinstance(result.get("elapsed_seconds"), (int, float)):
                    # The name a snapshot build gives its own time, apart from run_seconds for the whole run.
                    result = {key: value for key, value in result.items() if key != "elapsed_seconds"}
                    result["build_seconds"] = round(float(compiled["elapsed_seconds"]), 1)
                return result

            if mutation_scope is None:
                return await compile_now()
            # Taken here, not around the request: the request may return while the compile is still
            # reading the project, and no change may land under it.
            # Named as a stage only when there is a wait: a free project is taken at once.
            waiting = loop.call_later(0.25, run_status.report_stage, "waiting for a change to the project to finish")
            try:
                async with mutation_scope():
                    waiting.cancel()
                    return await compile_now()
            finally:
                waiting.cancel()

        def work() -> Dict[str, Any]:
            with label_pipeline(root, WORKING_TREE_LABEL):
                # Stopped while this run was still taking its label: nothing has been started.
                run_status.raise_if_stopped()
                future = asyncio.run_coroutine_threadsafe(compile_holding_the_project(), loop)
                pending.append(future)
                if run_status.stop_requested():
                    # The stop came after that check and before there was anything for it to cancel.
                    future.cancel()
                try:
                    return future.result()
                except concurrent.futures.CancelledError:
                    # The future reads as cancelled at once; the compiler is gone only when the task
                    # has unwound. A task cancelled before it ran a line has nothing to unwind, and
                    # would never say that it had.
                    if began.is_set():
                        unwound.wait(timeout=30)
                    raise run_status.RunStopped("The compile was stopped on request.") from None

        def cancel() -> None:
            # Cancelling the task ends the compiler's process tree and releases the project.
            for future in pending:
                future.cancel()

        try:
            return await background_runs.run(
                runs_directory(root, WORKING_TREE_LABEL),
                WORKING_TREE_LABEL,
                "gm_compile",
                work,
                wait_seconds=background_runs.call_wait_seconds(root, background),
                cancel=cancel,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "tool": "gm_compile", "error": str(exc), "error_type": type(exc).__name__}

    @mutating_tool
    async def gm_run(
        platform: RunnerPlatform | None = None,
        runtime: str = "VM",
        runtime_version: str | None = None,
        background: bool = False,
        output_location: str = "temp",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        enable_bridge: bool | None = None,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Build and run the project with Igor in its working tree.

        platform defaults to this OS. runtime is VM or YYC (GMS2 aliases accepted; GMRT is not
        supported). output_location: "temp" (IDE-style) or "project" (classic output folder).
        background=true launches the game and returns its pid and run_id at once; stop it with
        gm_run_stop. Otherwise the call waits for the game to exit and returns its output
        (output_mode full, tail of tail_lines, or none). enable_bridge starts the bridge for log
        capture and commands; by default it does when the bridge is installed.
        """
        selected_platform = platform or _default_target_platform()
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)

        args = argparse.Namespace(
            platform=selected_platform,
            runtime=runtime,
            runtime_version=runtime_version,
            background=background,
            output_location=output_location,
            project_root=project_root,
        )

        # Auto-detect bridge if not explicitly set
        bridge_enabled = False
        bridge_server = None
        bridge_start_error: str | None = None

        if enable_bridge is None or enable_bridge is True:
            try:
                from gms_helpers.bridge_installer import is_bridge_installed
                from gms_helpers.bridge_server import get_bridge_server

                if is_bridge_installed(str(_resolve_project_directory(project_root))):
                    if enable_bridge is not False:
                        # Start bridge server
                        bridge_server = get_bridge_server(
                            str(_resolve_project_directory(project_root)), create=True, port=0
                        )
                        if bridge_server and bridge_server.start():
                            bridge_enabled = True
                        else:
                            bridge_start_error = (
                                "Could not bind a local bridge socket; game launched without bridge credentials."
                            )
            except Exception as e:
                bridge_start_error = str(e)

        args.bridge_environment = (
            {"GMS_MCP_BRIDGE_PORT": str(bridge_server.port), "GMS_MCP_BRIDGE_TOKEN": bridge_server.token}
            if bridge_enabled and bridge_server
            else {}
        )

        # For background mode, we want to run directly and return quickly
        # The game will be launched and we'll return session info immediately
        if background:
            try:
                (
                    ok,
                    captured_stdout,
                    captured_stderr,
                    result_value,
                    error_text,
                    _exit_code,
                ) = await _run_direct_thread_shielded(
                    _run_direct_preserve_result,
                    handle_runner_run,
                    args,
                    project_root,
                    _default_timeout_seconds_for_cli_args(["run", "background-start"]),
                )
            except Exception as e:
                if bridge_server:
                    bridge_server.stop()
                return {"ok": False, "background": True, "error": str(e), "message": f"Failed to launch game: {e}"}

            if error_text:
                if bridge_server:
                    bridge_server.stop()
                return {
                    "ok": False,
                    "background": True,
                    "error": error_text,
                    "message": f"Failed to launch game: {error_text}",
                    "stdout": captured_stdout,
                    "stderr": captured_stderr,
                }

            if isinstance(result_value, dict):
                result: Dict[str, Any] = dict(result_value)
                result["bridge_enabled"] = bridge_enabled
                if bridge_enabled and bridge_server:
                    result["bridge_port"] = bridge_server.port
                    result["connected"] = bridge_server.is_connected
                    result["endpoint"] = bridge_server.hello
                if bridge_start_error:
                    result["bridge_error"] = bridge_start_error

                # If the handler reported failure, stop the bridge server to avoid leaving it running.
                if result.get("ok") is False and bridge_server:
                    bridge_server.stop()
                if result.get("ok") is False:
                    result.setdefault("stdout", captured_stdout)
                    result.setdefault("stderr", captured_stderr)
                return result

            # Fallback if somehow we got a bool or an unexpected return type
            ok_bool = bool(result_value) if isinstance(result_value, bool) else bool(ok)
            if not ok_bool and bridge_server:
                bridge_server.stop()
            return {
                "ok": ok_bool,
                "background": True,
                "bridge_enabled": bridge_enabled,
                "bridge_error": bridge_start_error,
                "message": "Game launched" if ok_bool else "Failed to launch game",
            }

        # Launch through the isolated typed worker so credentials never touch the MCP process environment.
        try:
            direct = await _run_direct_thread_shielded(
                _run_direct,
                handle_runner_run,
                args,
                project_root,
                _default_timeout_seconds_for_cli_args(["run", "start"]),
            )
            result = _apply_output_mode(
                direct.as_dict(),
                output_mode=output_mode,
                tail_lines=tail_lines,
                quiet=quiet,
            )
            result["bridge_enabled"] = bridge_enabled
            if bridge_enabled and bridge_server:
                result["bridge_port"] = bridge_server.port
            if bridge_start_error:
                result["bridge_error"] = bridge_start_error
            return result
        finally:
            if bridge_server:
                bridge_server.stop()

    @mutating_tool
    async def gm_run_stop(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Stop the game gm_run started, and its bridge, even from another session or after a restart.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_stop

        args = argparse.Namespace(project_root=project_root)

        # Stop bridge server if running
        bridge_stopped = False
        try:
            from gms_helpers.bridge_server import stop_bridge_server

            stop_bridge_server(str(repo_root))
            bridge_stopped = True
        except Exception:
            pass

        # Run directly for immediate response
        try:
            ok, _stdout, _stderr, result_value, error_text, _exit_code = await _run_direct_thread_shielded(
                _run_direct_preserve_result,
                handle_runner_stop,
                args,
                project_root,
                _default_timeout_seconds_for_cli_args(["run", "stop"]),
            )
        except Exception as e:
            return {
                "ok": False,
                "bridge_stopped": bridge_stopped,
                "error": str(e),
                "message": f"Error stopping game: {e}",
            }

        if error_text:
            return {
                "ok": False,
                "bridge_stopped": bridge_stopped,
                "error": error_text,
                "message": f"Error stopping game: {error_text}",
            }

        if isinstance(result_value, dict):
            result: Dict[str, Any] = dict(result_value)
            result["bridge_stopped"] = bridge_stopped
            return result

        ok_bool = bool(result_value) if isinstance(result_value, bool) else bool(ok)
        return {
            "ok": ok_bool,
            "bridge_stopped": bridge_stopped,
            "message": "Game stopped" if ok_bool else "Failed to stop game",
        }

    @mutating_tool
    async def gm_run_status(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Check whether the game gm_run started is still running, even from another session or after a restart.

        Returns has_session, running, run_id, pid, started_at and message.
        """
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_status

        args = argparse.Namespace(project_root=project_root)

        # Run directly for immediate response
        try:
            ok, _stdout, _stderr, result_value, error_text, _exit_code = await _run_direct_thread_shielded(
                _run_direct_preserve_result,
                handle_runner_status,
                args,
                project_root,
                _default_timeout_seconds_for_cli_args(["run", "status"]),
            )
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Error checking status: {e}"}

        if error_text:
            return {"ok": False, "error": error_text, "message": f"Error checking status: {error_text}"}

        if isinstance(result_value, dict):
            return result_value

        return {"ok": bool(ok), "running": bool(result_value), "message": "Status check completed"}
