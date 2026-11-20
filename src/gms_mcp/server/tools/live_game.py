"""Talk to a running game: start an isolated build with the runtime bridge, send commands, take screenshots."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

from .. import background_runs
from ..mcp_types import Context
from ..project import _resolve_project_directory
from ..results import MAX_INLINE_IMAGE_BYTES, attach_result_image


def _failure(tool: str, exc: Exception) -> Dict[str, Any]:
    return {"ok": False, "tool": tool, "error": str(exc), "error_type": type(exc).__name__}


def _attach_screenshot(root: Path, result: Dict[str, Any]) -> None:
    """Return the saved image with the result, so the caller does not need a second read to look."""
    relative = result.get("screenshot") if result.get("ok") else None
    if not isinstance(relative, str):
        return
    image = root / relative
    try:
        if image.is_symlink() or not image.is_file():
            return
        size = image.stat().st_size
        if size > MAX_INLINE_IMAGE_BYTES:
            result["image_attached"] = False
            result["message"] = f"The image is {size} bytes, too large to attach. Open the image file to look at it."
            return
        attach_result_image(image.read_bytes())
    except OSError:
        return
    result["image_attached"] = True
    result["message"] = "The image is attached to this result and saved at `screenshot`."


def register(mcp: Any, ContextType: Any) -> None:
    globals()["Context"] = ContextType

    @mcp.tool()
    async def gm_game_start(
        label: str = "live",
        isolate_paths: List[str] | None = None,
        yyp_entries: List[str] | None = None,
        base_only: bool = False,
        ref: str = "HEAD",
        connect_timeout_seconds: int = 60,
        runtime_version: str | None = None,
        background: bool = False,
        project_root: str = ".",
        ctx: Context | None = None,
    ) -> Dict[str, Any]:
        """
        Build a throwaway copy of the project, start the game and connect to it over the runtime bridge.

        The build takes minutes. A call that has no result after about 20 seconds returns status
        STILL_RUNNING with the build's stage, and the start carries on: follow it with
        gm_build_status(label=...), which returns this result once the game is up.
        background=true returns at once instead.

        After it returns status RUNNING you can drive the game with:
          gm_game_command("ping" | "help" | "state" | "console <console command line>" | "log_tail 50")
          gm_game_screenshot(name)   save and return a screenshot
          gm_game_log(lines)         the game's full log (every show_debug_message line)
          gm_game_stop()             stop this project session when finished
        Snapshot options (isolate_paths, yyp_entries, base_only, ref) work as in gm_snapshot_compile.
        Isolated macOS runs require runtime="VM"; YYC needs a separate native application.

        The game connects only if the project has a bridge endpoint enabled for this build that
        reads the GMS_MCP_BRIDGE_PORT environment variable. status RUNNING_NOT_CONNECTED means
        the game is up but has no such endpoint; BUILD_FAILED carries compiler errors.
        Needs a macOS host.
        """
        _ = ctx
        from gms_helpers import live_session

        from gms_helpers.snapshot_build import runs_directory, safe_label

        root = _resolve_project_directory(project_root)
        label = safe_label(label)  # the name the run is filed and reported under

        def work() -> Dict[str, Any]:
            return live_session.start(
                root,
                label=label,
                isolate_paths=isolate_paths,
                yyp_entries=yyp_entries,
                base_only=base_only,
                ref=ref,
                runtime_version=runtime_version,
                connect_timeout_seconds=float(connect_timeout_seconds),
            )

        try:
            run_dir = runs_directory(root, label)
            return await background_runs.run(
                run_dir, label, "gm_game_start", work, wait_seconds=background_runs.call_wait_seconds(root, background)
            )
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_game_start", exc)

    @mcp.tool()
    def gm_game_status(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """Report whether the live game started by gm_game_start is running and connected, and what its endpoint supports."""
        _ = ctx
        from gms_helpers import live_session

        return live_session.status(_resolve_project_directory(project_root))

    @mcp.tool()
    async def gm_game_command(
        command: str, timeout_seconds: float = 5.0, project_root: str = ".", ctx: Context | None = None
    ) -> Dict[str, Any]:
        """
        Send one command line to the live game and return its answer.

        Standard commands every bridge endpoint provides:
          ping                      -> "pong"
          help                      -> the commands this game supports
          state                     -> JSON: room, app/game state, fps, instance count, ...
          console <command line>    -> run a developer-console command; JSON with its output lines
          log_tail [count]          -> JSON with the game's most recent log lines
        A project can register more (call `help`). Structured answers come back parsed in `data`.
        Use gm_game_screenshot for screenshots: it also collects the image file.
        """
        _ = ctx
        from gms_helpers import live_session

        root = _resolve_project_directory(project_root)
        try:
            return await asyncio.to_thread(lambda: live_session.command(root, command, timeout_seconds))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_game_command", exc)

    @mcp.tool()
    async def gm_game_screenshot(
        name: str = "shot", project_root: str = ".", ctx: Context | None = None
    ) -> Dict[str, Any]:
        """
        Take a screenshot of the live game and return the image.

        The image is attached to the result and saved inside .gms_mcp/runs/<label>/shots/ (`screenshot`).
        A very large image is saved only; `image_attached` says which happened.
        """
        _ = ctx
        from gms_helpers import live_session

        root = _resolve_project_directory(project_root)
        try:
            result = await asyncio.to_thread(lambda: live_session.screenshot(root, name))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_game_screenshot", exc)
        _attach_screenshot(root, result)
        return result

    @mcp.tool()
    def gm_game_log(
        lines: int = 100, pattern: str = "", project_root: str = ".", ctx: Context | None = None
    ) -> Dict[str, Any]:
        """
        Read the live game's log file: every show_debug_message line and runtime error, not only bridge logs.

        pattern is an optional regular expression that keeps only matching lines.
        """
        _ = ctx
        from gms_helpers import live_session

        try:
            return live_session.game_log(_resolve_project_directory(project_root), lines, pattern or None)
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_game_log", exc)

    @mcp.tool()
    async def gm_game_stop(project_root: str = ".", ctx: Context | None = None) -> Dict[str, Any]:
        """Stop the live game, release this project's runtime lease, and return where its log and screenshots were saved."""
        _ = ctx
        from gms_helpers import live_session

        root = _resolve_project_directory(project_root)
        try:
            return await asyncio.to_thread(lambda: live_session.stop(root))
        except Exception as exc:  # noqa: BLE001
            return _failure("gm_game_stop", exc)
