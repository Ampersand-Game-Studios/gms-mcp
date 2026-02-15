from __future__ import annotations

import argparse
from typing import Any, Dict

from ..dispatch import _run_with_fallback
from ..mcp_types import Context
from ..platform import _default_target_platform
from ..project import _ensure_cli_on_sys_path, _resolve_repo_root


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

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
                            if not quiet:
                                print(f"[BRIDGE] Server started on port {bridge_server.port}")
            except Exception as e:
                if not quiet:
                    print(f"[BRIDGE] Failed to start bridge: {e}")
        
        # For background mode, we want to run directly and return quickly
        # The game will be launched and we'll return session info immediately
        if background:
            # Run the handler directly - it will return session info without blocking
            try:
                result = handle_runner_run(args)
                
                # If result is a dict (background mode returns dict), add bridge info
                if isinstance(result, dict):
                    result["bridge_enabled"] = bridge_enabled
                    if bridge_enabled and bridge_server:
                        result["bridge_port"] = bridge_server.port
                    return result
                
                # Fallback if somehow we got a bool
                return {
                    "ok": bool(result),
                    "background": True,
                    "bridge_enabled": bridge_enabled,
                    "message": "Game launched" if result else "Failed to launch game",
                }
            except Exception as e:
                # Stop bridge on failure
                if bridge_server:
                    bridge_server.stop()
                return {
                    "ok": False,
                    "background": True,
                    "error": str(e),
                    "message": f"Failed to launch game: {e}",
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
            result = handle_runner_stop(args)
            if isinstance(result, dict):
                result["bridge_stopped"] = bridge_stopped
                return result
            return {"ok": bool(result), "bridge_stopped": bridge_stopped, "message": "Game stopped" if result else "Failed to stop game"}
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Error stopping game: {e}"}

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
            result = handle_runner_status(args)
            if isinstance(result, dict):
                return result
            return {"running": bool(result), "message": "Status check completed"}
        except Exception as e:
            return {"ok": False, "error": str(e), "message": f"Error checking status: {e}"}
