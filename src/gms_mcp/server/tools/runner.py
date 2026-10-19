from __future__ import annotations

import argparse
from typing import Any, Dict

from ..direct import _run_direct, _run_direct_thread_shielded
from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..platform import _default_target_platform
from ..project import _ensure_cli_on_sys_path, _resolve_project_directory, _resolve_repo_root
from ..subprocess_runner import _default_timeout_seconds_for_cli_args
from ..tool_types import OutputMode, RunnerPlatform


def register(mcp: Any, ContextType: Any, *, read_only: bool = False) -> None:
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
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: OutputMode = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """Compile the project using Igor."""
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

        return await _run_with_fallback(
            direct_handler=handle_runner_compile,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

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
        Run the project using Igor.

        Args:
            platform: Target platform (default: host OS)
            runtime: Runtime type VM or YYC (default: VM). GMS2 VM/YYC aliases are accepted;
                     GMRT labels are rejected until GameMaker documents Igor CLI support.
            runtime_version: Specific runtime version to use
            background: If True, launch game and return immediately without waiting.
                        The game will run in the background and can be stopped with gm_run_stop.
                        Returns session info (pid, run_id) for tracking.
            output_location: 'temp' (IDE-style) or 'project' (classic output folder)
            project_root: Path to project root
            prefer_cli: Force CLI execution mode
            output_mode: Output format (full, tail, none)
            tail_lines: Number of lines to show in tail mode
            quiet: Suppress verbose output
            enable_bridge: If True, start a verified session-owned bridge (macOS).
                          If None (default), use the project's bridge.enabled setting (default True).
                          If False, explicitly disable bridge even if installed.

        Returns:
            If background=True: Dict with session info (ok, pid, run_id, message, bridge_enabled)
            If background=False: Dict with full execution result including stdout

        macOS launches retain their session and bridge in this MCP server;
        prefer_cli applies only to other targets.
        """
        selected_platform = platform or _default_target_platform()
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_run

        if selected_platform == "macOS":
            # A disposable CLI worker cannot own a persistent bridge: its
            # listener and session registry vanish as soon as it returns.
            # This path uses explicit roots throughout and emits no CLI output.
            from gms_helpers.runner import GameMakerRunner

            root = _resolve_project_directory(project_root)
            managed_runner = GameMakerRunner(root, runtime_version=runtime_version)
            managed_result = await _run_direct_thread_shielded(
                managed_runner.run_project_direct,
                selected_platform,
                runtime,
                background,
                output_location,
                enable_bridge=enable_bridge,
            )
            if isinstance(managed_result, dict):
                return managed_result
            return {
                "ok": bool(managed_result),
                "background": background,
                "bridge_enabled": False,
                "message": managed_runner.last_failure_message or "Game launch completed",
            }

        args = argparse.Namespace(
            platform=selected_platform,
            runtime=runtime,
            runtime_version=runtime_version,
            background=background,
            output_location=output_location,
            project_root=project_root,
            enable_bridge=enable_bridge,
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
                return {"ok": False, "background": True, "error": str(e), "message": f"Failed to launch game: {e}"}

            if error_text:
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
                result.setdefault("bridge_enabled", False)
                if result.get("ok") is False:
                    result.setdefault("stdout", captured_stdout)
                    result.setdefault("stderr", captured_stderr)
                return result

            # Fallback if somehow we got a bool or an unexpected return type
            ok_bool = bool(result_value) if isinstance(result_value, bool) else bool(ok)
            return {
                "ok": ok_bool,
                "background": True,
                "bridge_enabled": False,
                "message": "Game launched" if ok_bool else "Failed to launch game",
            }

        # For foreground mode, use the standard fallback mechanism
        cli_args = [
            "run",
            "start",
            "--platform",
            selected_platform,
            "--runtime",
            runtime,
            "--output-location",
            output_location,
        ]
        if runtime_version:
            cli_args.extend(["--runtime-version", runtime_version])
        if enable_bridge is not None:
            cli_args.append("--enable-bridge" if enable_bridge else "--no-enable-bridge")

        return await _run_with_fallback(
            direct_handler=handle_runner_run,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
            ctx=ctx,
        )

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
        Stop the running game (if any).

        Uses persistent session tracking to find and stop the game,
        even if called from a different process or after MCP server restart.
        Also stops the bridge server if it was running.

        Returns:
            Dict with result of stop operation (ok, message)
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
        Check whether the game is running.

        Uses persistent session tracking to check status,
        even if called from a different process or after MCP server restart.

        Returns:
            Dict with session info:
            - has_session: bool - whether a session file exists
            - running: bool - whether the game process is still alive
            - run_id: str - unique session identifier
            - pid: int - process ID
            - started_at: str - ISO timestamp when game was launched
            - message: str - human-readable status message
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
