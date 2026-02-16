from __future__ import annotations

import argparse
from typing import Any, Dict

from ..direct import _capture_output, _pushd
from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..platform import _default_target_platform
from ..project import _ensure_cli_on_sys_path, _resolve_project_directory, _resolve_repo_root


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    def _run_direct_preserve_result(handler: Any, args: argparse.Namespace, project_root: str) -> tuple[bool, str, str, Any, str | None, int | None]:
        """
        Run a handler in-process while capturing stdout/stderr, but preserve the handler's return value.

        This is required for runner subcommands like `run start --background` where the handler returns a dict
        (pid/run_id/etc). Using the generic direct-execution path discards return values intentionally.
        """
        project_directory = _resolve_project_directory(project_root)

        def _invoke() -> Any:
            from gms_helpers.utils import validate_working_directory

            with _pushd(project_directory):
                validate_working_directory()
                # Normalize project_root after chdir so downstream handlers behave consistently.
                setattr(args, "project_root", ".")
                return handler(args)

        return _capture_output(_invoke)

    # -----------------------------
    # Runner tools
    # -----------------------------
    @mcp.tool()
    async def gm_compile(
        platform: str | None = None,
        runtime: str = "VM",
        runtime_version: str | None = None,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
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

    @mcp.tool()
    async def gm_run(
        platform: str | None = None,
        runtime: str = "VM",
        runtime_version: str | None = None,
        background: bool = False,
        output_location: str = "temp",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
        enable_bridge: bool | None = None,
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Run the project using Igor.
        
        Args:
            platform: Target platform (default: host OS)
            runtime: Runtime type VM or YYC (default: VM)
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
            enable_bridge: If True, start bridge server for log capture and commands.
                          If None (default), auto-detect based on whether bridge is installed.
                          If False, explicitly disable bridge even if installed.
            
        Returns:
            If background=True: Dict with session info (ok, pid, run_id, message, bridge_enabled)
            If background=False: Dict with full execution result including stdout
        """
        selected_platform = platform or _default_target_platform()
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_run

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
                
                if is_bridge_installed(str(repo_root)):
                    if enable_bridge is not False:
                        # Start bridge server
                        bridge_server = get_bridge_server(str(repo_root), create=True)
                        if bridge_server and bridge_server.start():
                            bridge_enabled = True
            except Exception as e:
                bridge_start_error = str(e)
        
        # For background mode, we want to run directly and return quickly
        # The game will be launched and we'll return session info immediately
        if background:
            try:
                ok, _stdout, _stderr, result_value, error_text, _exit_code = _run_direct_preserve_result(
                    handle_runner_run, args, project_root
                )
            except Exception as e:
                if bridge_server:
                    bridge_server.stop()
                return {"ok": False, "background": True, "error": str(e), "message": f"Failed to launch game: {e}"}

            if error_text:
                if bridge_server:
                    bridge_server.stop()
                return {"ok": False, "background": True, "error": error_text, "message": f"Failed to launch game: {error_text}"}

            if isinstance(result_value, dict):
                result: Dict[str, Any] = dict(result_value)
                result["bridge_enabled"] = bridge_enabled
                if bridge_enabled and bridge_server:
                    result.setdefault("bridge_port", bridge_server.port)
                if bridge_start_error:
                    result.setdefault("bridge_error", bridge_start_error)

                # If the handler reported failure, stop the bridge server to avoid leaving it running.
                if result.get("ok") is False and bridge_server:
                    bridge_server.stop()
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

    @mcp.tool()
    async def gm_run_stop(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
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
            ok, _stdout, _stderr, result_value, error_text, _exit_code = _run_direct_preserve_result(
                handle_runner_stop, args, project_root
            )
        except Exception as e:
            return {"ok": False, "bridge_stopped": bridge_stopped, "error": str(e), "message": f"Error stopping game: {e}"}

        if error_text:
            return {"ok": False, "bridge_stopped": bridge_stopped, "error": error_text, "message": f"Error stopping game: {error_text}"}

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

    @mcp.tool()
    async def gm_run_status(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
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
            ok, _stdout, _stderr, result_value, error_text, _exit_code = _run_direct_preserve_result(
                handle_runner_status, args, project_root
            )
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Error checking status: {e}"}

        if error_text:
            return {"ok": False, "error": error_text, "message": f"Error checking status: {error_text}"}

        if isinstance(result_value, dict):
            return result_value

        return {"ok": bool(ok), "running": bool(result_value), "message": "Status check completed"}
