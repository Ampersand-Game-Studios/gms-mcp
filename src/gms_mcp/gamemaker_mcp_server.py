#!/usr/bin/env python3
"""
GameMaker MCP Server

Exposes common GameMaker project actions as MCP tools by reusing the existing
Python helper modules in `gms_helpers`.

Design:
- Prefer **direct imports** (call handlers in-process).
- If a direct call throws, **fallback** to running the `gms` CLI as a module (`python -m gms_helpers.gms`).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def _list_yyp_files(directory: Path) -> List[Path]:
    try:
        return sorted(directory.glob("*.yyp"))
    except Exception:
        return []


def _search_upwards_for_yyp(start_dir: Path) -> Optional[Path]:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        if _list_yyp_files(candidate):
            return candidate
    return None


def _search_upwards_for_gamemaker_yyp(start_dir: Path) -> Optional[Path]:
    start_dir = Path(start_dir).resolve()
    for candidate in [start_dir, *start_dir.parents]:
        gm = candidate / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm
    return None


def _resolve_project_directory_no_deps(project_root: str | None) -> Path:
    """
    Resolve the GameMaker project directory (the folder containing a .yyp)
    without importing `gms_helpers` (so we don't need to know repo root yet).
    """
    candidates: List[Path] = []
    if project_root is not None:
        root_str = str(project_root).strip()
        if root_str and root_str != ".":
            candidates.append(Path(root_str))

    # Environment overrides (handy for agents)
    env_gm_root = os.environ.get("GM_PROJECT_ROOT")
    if env_gm_root:
        candidates.append(Path(env_gm_root))
    env_root = os.environ.get("PROJECT_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(Path.cwd())

    tried: List[str] = []
    for raw in candidates:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        if p.is_file():
            p = p.parent
        tried.append(str(p))
        if not p.exists() or not p.is_dir():
            continue

        if _list_yyp_files(p):
            return p

        gm = p / "gamemaker"
        if gm.exists() and gm.is_dir() and _list_yyp_files(gm):
            return gm

        found = _search_upwards_for_yyp(p)
        if found:
            return found

        found_gm = _search_upwards_for_gamemaker_yyp(p)
        if found_gm:
            return found_gm

    raise FileNotFoundError(
        "Could not find a GameMaker project directory (.yyp) from the provided project_root or CWD. "
        f"Tried: {tried}"
    )


def _resolve_repo_root(project_root: str | None) -> Path:
    """
    Compatibility shim: older versions of this server expected a "repo root" that contained `cli/`.

    In the packaged install, the tool code is importable as Python packages and does not require a repo root.
    """
    _ = project_root
    return Path(__file__).resolve().parents[1]


def _ensure_cli_on_sys_path(_repo_root: Path) -> None:
    # Compatibility shim (no-op in installed mode).
    return None


@contextlib.contextmanager
def _pushd(target_directory: Path):
    """Temporarily change working directory."""
    previous_directory = Path.cwd()
    os.chdir(target_directory)
    try:
        yield
    finally:
        os.chdir(previous_directory)


@dataclass
class ToolRunResult:
    ok: bool
    stdout: str
    stderr: str
    direct_used: bool
    exit_code: Optional[int] = None
    error: Optional[str] = None
    direct_error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "direct_used": self.direct_used,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
            "direct_error": self.direct_error,
        }


def _apply_output_mode(
    result: Dict[str, Any],
    *,
    output_mode: str = "full",
    tail_lines: int = 120,
    max_chars: int = 40000,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Pure output-shaping helper (no side effects, no command execution).
    """
    normalized_mode = output_mode
    if quiet and output_mode == "full":
        normalized_mode = "tail"

    def _tail(text: str) -> Tuple[str, bool]:
        if not text:
            return "", False
        lines = text.splitlines()
        if tail_lines > 0 and len(lines) > tail_lines:
            lines = lines[-tail_lines:]
        out = "\n".join(lines)
        if max_chars > 0 and len(out) > max_chars:
            out = out[-max_chars:]
            return out, True
        return out, False

    if normalized_mode not in ("full", "tail", "none"):
        normalized_mode = "tail"

    stdout_text = str(result.get("stdout", "") or "")
    stderr_text = str(result.get("stderr", "") or "")

    if normalized_mode == "full":
        return result
    if normalized_mode == "none":
        result["stdout"] = ""
        result["stderr"] = ""
        result["stdout_truncated"] = bool(stdout_text)
        result["stderr_truncated"] = bool(stderr_text)
        return result

    stdout_tail, stdout_truncated = _tail(stdout_text)
    stderr_tail, stderr_truncated = _tail(stderr_text)
    result["stdout"] = stdout_tail
    result["stderr"] = stderr_tail
    result["stdout_truncated"] = stdout_truncated or (tail_lines > 0 and len(stdout_text.splitlines()) > tail_lines)
    result["stderr_truncated"] = stderr_truncated or (tail_lines > 0 and len(stderr_text.splitlines()) > tail_lines)
    return result


def _resolve_project_directory(project_root: str | None) -> Path:
    # Prefer in-repo resolution (no imports) so server doesn't depend on process CWD.
    return _resolve_project_directory_no_deps(project_root)


def _find_yyp_file(project_directory: Path) -> Optional[str]:
    try:
        yyp_files = sorted(project_directory.glob("*.yyp"))
        if not yyp_files:
            return None
        return yyp_files[0].name
    except Exception:
        return None


def _capture_output(callable_to_run: Callable[[], Any]) -> Tuple[bool, str, str, Any, Optional[str]]:
    # Use TextIOWrapper over BytesIO so captured streams behave like real stdio
    # (notably: some project code expects sys.stdout.buffer to exist).
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    stdout_buffer = io.TextIOWrapper(stdout_bytes, encoding="utf-8", errors="replace", line_buffering=True)
    stderr_buffer = io.TextIOWrapper(stderr_bytes, encoding="utf-8", errors="replace", line_buffering=True)
    result_value: Any = None
    error_text: Optional[str] = None

    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        try:
            result_value = callable_to_run()
            ok = bool(result_value) if isinstance(result_value, bool) else True
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

    return ok, stdout_text, stderr_text, result_value, error_text


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

    ok, stdout_text, stderr_text, _result_value, error_text = _capture_output(_invoke)
    return ToolRunResult(
        ok=ok,
        stdout=stdout_text,
        stderr=stderr_text,
        direct_used=True,
        error=error_text,
    )


def _run_gms_inprocess(cli_args: List[str], project_root: str | None) -> ToolRunResult:
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

    ok, stdout_text, stderr_text, _result_value, error_text = _capture_output(_invoke)
    return ToolRunResult(
        ok=ok,
        stdout=stdout_text,
        stderr=stderr_text,
        direct_used=True,
        exit_code=0 if ok else None,
        error=error_text,
    )


def _run_cli(cli_args: List[str], project_root: str | None, timeout_seconds: int | None = None) -> ToolRunResult:
    project_root_value = project_root or "."
    project_directory = _resolve_project_directory(project_root)
    cmd = [sys.executable, "-m", "gms_helpers.gms", "--project-root", str(project_root_value), *cli_args]

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(project_directory),
            capture_output=True,
            text=True,
            timeout=timeout_seconds if (timeout_seconds is not None and timeout_seconds > 0) else None,
        )
        ok = completed.returncode == 0
        return ToolRunResult(
            ok=ok,
            stdout=completed.stdout,
            stderr=completed.stderr,
            direct_used=False,
            exit_code=completed.returncode,
            error=None if ok else f"CLI exited with code {completed.returncode}",
        )
    except subprocess.TimeoutExpired as e:
        stdout_text = ""
        stderr_text = ""
        try:
            stdout_text = e.stdout or ""
            stderr_text = e.stderr or ""
        except Exception:
            pass
        return ToolRunResult(
            ok=False,
            stdout=stdout_text,
            stderr=stderr_text,
            direct_used=False,
            exit_code=None,
            error=f"CLI timed out after {timeout_seconds}s",
        )
    except Exception:
        return ToolRunResult(
            ok=False,
            stdout="",
            stderr="",
            direct_used=False,
            exit_code=None,
            error=traceback.format_exc(),
        )


def _run_with_fallback(
    *,
    direct_handler: Callable[[argparse.Namespace], Any],
    direct_args: argparse.Namespace,
    cli_args: List[str],
    project_root: str | None,
    prefer_cli: bool,
    output_mode: str = "full",
    tail_lines: int = 120,
    max_chars: int = 40000,
    quiet: bool = False,
    timeout_seconds: int | None = None,
) -> Dict[str, Any]:
    if prefer_cli:
        return _apply_output_mode(
            _run_cli(cli_args, project_root, timeout_seconds=timeout_seconds).as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )

    direct_result = _run_direct(direct_handler, direct_args, project_root)
    if direct_result.ok:
        return _apply_output_mode(
            direct_result.as_dict(),
            output_mode=output_mode,
            tail_lines=tail_lines,
            max_chars=max_chars,
            quiet=quiet,
        )

    # If the direct call threw (or otherwise failed), fall back to CLI for resilience.
    cli_result = _run_cli(cli_args, project_root, timeout_seconds=timeout_seconds)
    cli_result.direct_error = direct_result.error or "Direct call failed"
    return _apply_output_mode(
        cli_result.as_dict(),
        output_mode=output_mode,
        tail_lines=tail_lines,
        max_chars=max_chars,
        quiet=quiet,
    )


def build_server():
    """
    Create and return the MCP server instance.
    Kept in a function so importing this module doesn't require MCP installed.
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("GameMaker MCP")

    @mcp.tool()
    def gm_project_info(project_root: str = ".") -> Dict[str, Any]:
        """
        Resolve GameMaker project directory (where the .yyp lives) and return basic info.
        """
        project_directory = _resolve_project_directory_no_deps(project_root)
        return {
            "project_directory": str(project_directory),
            "yyp": _find_yyp_file(project_directory),
            "tools_mode": "installed",
        }

    @mcp.tool()
    def gm_cli(
        args: List[str],
        project_root: str = ".",
        prefer_cli: bool = True,
        timeout_seconds: int = 30,
        output_mode: str = "tail",
        tail_lines: int = 120,
        quiet: bool = True,
        fallback_to_subprocess: bool = True,
    ) -> Dict[str, Any]:
        """
        Run the existing `gms` CLI.

        Default behavior is **in-process** (direct import) to avoid subprocess hangs.
        If that fails and `fallback_to_subprocess=true`, it will shell out as a backup.
        Example args: ["maintenance", "auto", "--fix", "--verbose"]
        """
        # prefer_cli is accepted to match the other tools' signature style.
        _ = prefer_cli
        # Prefer in-process execution first (root cause fix for hanging subprocess calls).
        inprocess_dict = _run_gms_inprocess(args, project_root).as_dict()
        shaped_inprocess = _apply_output_mode(
            inprocess_dict,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )
        if shaped_inprocess.get("ok"):
            return shaped_inprocess

        if not fallback_to_subprocess:
            shaped_inprocess["error"] = shaped_inprocess.get("error") or "In-process gms execution failed"
            return shaped_inprocess

        # Backup: subprocess with timeout (damage control only).
        cli_dict = _run_cli(args, project_root, timeout_seconds=timeout_seconds).as_dict()
        cli_dict["direct_error"] = shaped_inprocess.get("error") or "In-process gms execution failed"
        return _apply_output_mode(
            cli_dict,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Asset creation tools
    # -----------------------------
    @mcp.tool()
    def gm_create_script(
        name: str,
        parent_path: str,
        constructor: bool = False,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a GameMaker script asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="script",
            name=name,
            parent_path=parent_path,
            constructor=constructor,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "script",
            name,
            "--parent-path",
            parent_path,
        ]
        if constructor:
            cli_args.append("--constructor")
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_object(
        name: str,
        parent_path: str,
        sprite_id: str = "",
        parent_object: str = "",
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a GameMaker object asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="object",
            name=name,
            parent_path=parent_path,
            sprite_id=sprite_id or None,
            parent_object=parent_object or None,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "object",
            name,
            "--parent-path",
            parent_path,
        ]
        if sprite_id:
            cli_args.extend(["--sprite-id", sprite_id])
        if parent_object:
            cli_args.extend(["--parent-object", parent_object])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_sprite(
        name: str,
        parent_path: str,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a GameMaker sprite asset (includes required image structure via your helpers)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sprite",
            name=name,
            parent_path=parent_path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "sprite",
            name,
            "--parent-path",
            parent_path,
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_room(
        name: str,
        parent_path: str,
        width: int = 1024,
        height: int = 768,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a GameMaker room asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="room",
            name=name,
            parent_path=parent_path,
            width=width,
            height=height,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "room",
            name,
            "--parent-path",
            parent_path,
            "--width",
            str(width),
            "--height",
            str(height),
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_folder(
        name: str,
        path: str,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a GameMaker folder asset (`folders/My Folder.yy`)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="folder",
            name=name,
            path=path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "folder",
            name,
            "--path",
            path,
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_font(
        name: str,
        parent_path: str,
        font_name: str = "Arial",
        size: int = 12,
        bold: bool = False,
        italic: bool = False,
        aa_level: int = 1,
        uses_sdf: bool = True,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a GameMaker font asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="font",
            name=name,
            parent_path=parent_path,
            font_name=font_name,
            size=size,
            bold=bold,
            italic=italic,
            aa_level=aa_level,
            uses_sdf=uses_sdf,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )

        cli_args = ["asset", "create", "font", name, "--parent-path", parent_path, "--font-name", font_name, "--size", str(size), "--aa-level", str(aa_level)]
        if bold:
            cli_args.append("--bold")
        if italic:
            cli_args.append("--italic")
        cli_args.extend(["--uses-sdf" if uses_sdf else "--no-uses-sdf"])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_shader(
        name: str,
        parent_path: str,
        shader_type: int = 1,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a GameMaker shader asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="shader",
            name=name,
            parent_path=parent_path,
            shader_type=shader_type,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "shader", name, "--parent-path", parent_path, "--shader-type", str(shader_type)]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_animcurve(
        name: str,
        parent_path: str,
        curve_type: str = "linear",
        channel_name: str = "curve",
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create an animation curve asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="animcurve",
            name=name,
            parent_path=parent_path,
            curve_type=curve_type,
            channel_name=channel_name,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "animcurve", name, "--parent-path", parent_path, "--curve-type", curve_type, "--channel-name", channel_name]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_sound(
        name: str,
        parent_path: str,
        volume: float = 1.0,
        pitch: float = 1.0,
        sound_type: int = 0,
        bitrate: int = 128,
        sample_rate: int = 44100,
        format: int = 0,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a sound asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sound",
            name=name,
            parent_path=parent_path,
            volume=volume,
            pitch=pitch,
            sound_type=sound_type,
            bitrate=bitrate,
            sample_rate=sample_rate,
            format=format,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "sound",
            name,
            "--parent-path",
            parent_path,
            "--volume",
            str(volume),
            "--pitch",
            str(pitch),
            "--sound-type",
            str(sound_type),
            "--bitrate",
            str(bitrate),
            "--sample-rate",
            str(sample_rate),
            "--format",
            str(format),
        ]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_path(
        name: str,
        parent_path: str,
        closed: bool = False,
        precision: int = 4,
        path_type: str = "straight",
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a path asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="path",
            name=name,
            parent_path=parent_path,
            closed=closed,
            precision=precision,
            path_type=path_type,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "path", name, "--parent-path", parent_path, "--precision", str(precision), "--path-type", path_type]
        if closed:
            cli_args.append("--closed")
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_tileset(
        name: str,
        parent_path: str,
        sprite_id: str = "",
        tile_width: int = 32,
        tile_height: int = 32,
        tile_xsep: int = 0,
        tile_ysep: int = 0,
        tile_xoff: int = 0,
        tile_yoff: int = 0,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a tileset asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="tileset",
            name=name,
            parent_path=parent_path,
            sprite_id=sprite_id or None,
            tile_width=tile_width,
            tile_height=tile_height,
            tile_xsep=tile_xsep,
            tile_ysep=tile_ysep,
            tile_xoff=tile_xoff,
            tile_yoff=tile_yoff,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = [
            "asset",
            "create",
            "tileset",
            name,
            "--parent-path",
            parent_path,
            "--tile-width",
            str(tile_width),
            "--tile-height",
            str(tile_height),
            "--tile-xsep",
            str(tile_xsep),
            "--tile-ysep",
            str(tile_ysep),
            "--tile-xoff",
            str(tile_xoff),
            "--tile-yoff",
            str(tile_yoff),
        ]
        if sprite_id:
            cli_args.extend(["--sprite-id", sprite_id])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_timeline(
        name: str,
        parent_path: str,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a timeline asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="timeline",
            name=name,
            parent_path=parent_path,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "timeline", name, "--parent-path", parent_path]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_sequence(
        name: str,
        parent_path: str,
        length: float = 60.0,
        playback_speed: float = 30.0,
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a sequence asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="sequence",
            name=name,
            parent_path=parent_path,
            length=length,
            playback_speed=playback_speed,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "sequence", name, "--parent-path", parent_path, "--length", str(length), "--playback-speed", str(playback_speed)]
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_create_note(
        name: str,
        parent_path: str,
        content: str = "",
        skip_maintenance: bool = False,
        no_auto_fix: bool = False,
        maintenance_verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Create a note asset."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_create

        args = argparse.Namespace(
            asset_type="note",
            name=name,
            parent_path=parent_path,
            content=content if content else None,
            skip_maintenance=skip_maintenance,
            no_auto_fix=no_auto_fix,
            maintenance_verbose=maintenance_verbose,
            project_root=project_root,
        )
        cli_args = ["asset", "create", "note", name, "--parent-path", parent_path]
        if content:
            cli_args.extend(["--content", content])
        if skip_maintenance:
            cli_args.append("--skip-maintenance")
        if no_auto_fix:
            cli_args.append("--no-auto-fix")
        cli_args.extend(["--maintenance-verbose" if maintenance_verbose else "--no-maintenance-verbose"])

        return _run_with_fallback(
            direct_handler=handle_asset_create,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_asset_delete(
        asset_type: str,
        name: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Delete an asset (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.asset_commands import handle_asset_delete

        args = argparse.Namespace(
            asset_type=asset_type,
            name=name,
            dry_run=dry_run,
            project_root=project_root,
        )
        cli_args = ["asset", "delete", asset_type, name]
        if dry_run:
            cli_args.append("--dry-run")

        return _run_with_fallback(
            direct_handler=handle_asset_delete,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Maintenance tools
    # -----------------------------
    @mcp.tool()
    def gm_maintenance_auto(
        fix: bool = False,
        verbose: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Run your auto-maintenance pipeline."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_auto

        args = argparse.Namespace(
            fix=fix,
            verbose=verbose,
            project_root=project_root,
        )
        cli_args = ["maintenance", "auto"]
        if fix:
            cli_args.append("--fix")
        cli_args.append("--verbose" if verbose else "--no-verbose")

        return _run_with_fallback(
            direct_handler=handle_maintenance_auto,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_lint(
        fix: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Run maintenance lint (optionally with fixes)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_lint

        args = argparse.Namespace(fix=fix, project_root=project_root)
        cli_args = ["maintenance", "lint"]
        if fix:
            cli_args.append("--fix")

        return _run_with_fallback(
            direct_handler=handle_maintenance_lint,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_validate_json(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Validate JSON files in the project."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_validate_json

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["maintenance", "validate-json"]

        return _run_with_fallback(
            direct_handler=handle_maintenance_validate_json,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_list_orphans(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Find orphaned and missing assets."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_list_orphans

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["maintenance", "list-orphans"]

        return _run_with_fallback(
            direct_handler=handle_maintenance_list_orphans,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_prune_missing(
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Remove missing asset references from project file."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_prune_missing

        args = argparse.Namespace(dry_run=dry_run, project_root=project_root)
        cli_args = ["maintenance", "prune-missing"]
        if dry_run:
            cli_args.append("--dry-run")

        return _run_with_fallback(
            direct_handler=handle_maintenance_prune_missing,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_validate_paths(
        strict_disk_check: bool = False,
        include_parent_folders: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Validate folder paths referenced in assets."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_validate_paths

        args = argparse.Namespace(
            strict_disk_check=strict_disk_check,
            include_parent_folders=include_parent_folders,
            project_root=project_root,
        )
        cli_args = ["maintenance", "validate-paths"]
        if strict_disk_check:
            cli_args.append("--strict-disk-check")
        if include_parent_folders:
            cli_args.append("--include-parent-folders")

        return _run_with_fallback(
            direct_handler=handle_maintenance_validate_paths,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_dedupe_resources(
        auto: bool = False,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Remove duplicate resource entries from .yyp."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_dedupe_resources

        args = argparse.Namespace(auto=auto, dry_run=dry_run, project_root=project_root)
        cli_args = ["maintenance", "dedupe-resources"]
        if auto:
            cli_args.append("--auto")
        if dry_run:
            cli_args.append("--dry-run")

        return _run_with_fallback(
            direct_handler=handle_maintenance_dedupe_resources,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_sync_events(
        fix: bool = False,
        object: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Synchronize object events (dry-run unless fix=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_sync_events

        args = argparse.Namespace(fix=fix, object=object if object else None, project_root=project_root)
        cli_args = ["maintenance", "sync-events"]
        if fix:
            cli_args.append("--fix")
        if object:
            cli_args.extend(["--object", object])

        return _run_with_fallback(
            direct_handler=handle_maintenance_sync_events,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_clean_old_files(
        delete: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Remove .old.yy backup files (dry-run unless delete=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_clean_old_files

        args = argparse.Namespace(delete=delete, project_root=project_root)
        cli_args = ["maintenance", "clean-old-files"]
        if delete:
            cli_args.append("--delete")

        return _run_with_fallback(
            direct_handler=handle_maintenance_clean_old_files,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_clean_orphans(
        delete: bool = False,
        skip_types: List[str] | None = None,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Remove orphaned asset files (dry-run unless delete=true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_clean_orphans

        skip_types_value = skip_types if skip_types is not None else ["folder"]
        args = argparse.Namespace(delete=delete, skip_types=skip_types_value, project_root=project_root)
        cli_args = ["maintenance", "clean-orphans"]
        if delete:
            cli_args.append("--delete")
        if skip_types is not None:
            cli_args.append("--skip-types")
            cli_args.extend(skip_types_value)

        return _run_with_fallback(
            direct_handler=handle_maintenance_clean_orphans,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_maintenance_fix_issues(
        verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Run comprehensive maintenance with fixes enabled."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.maintenance_commands import handle_maintenance_fix_issues

        args = argparse.Namespace(verbose=verbose, project_root=project_root)
        cli_args = ["maintenance", "fix-issues"]
        if verbose:
            cli_args.append("--verbose")

        return _run_with_fallback(
            direct_handler=handle_maintenance_fix_issues,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Runner tools
    # -----------------------------
    @mcp.tool()
    def gm_compile(
        platform: str = "Windows",
        runtime: str = "VM",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Compile the project using Igor."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_compile

        args = argparse.Namespace(
            platform=platform,
            runtime=runtime,
            project_root=project_root,
        )
        cli_args = ["run", "compile", "--platform", platform, "--runtime", runtime]

        return _run_with_fallback(
            direct_handler=handle_runner_compile,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_run(
        platform: str = "Windows",
        runtime: str = "VM",
        background: bool = False,
        output_location: str = "temp",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Run the project using Igor (stitch/classic approaches handled by your runner)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_run

        args = argparse.Namespace(
            platform=platform,
            runtime=runtime,
            background=background,
            output_location=output_location,
            project_root=project_root,
        )
        cli_args = [
            "run",
            "start",
            "--platform",
            platform,
            "--runtime",
            runtime,
            "--output-location",
            output_location,
        ]
        if background:
            cli_args.append("--background")

        return _run_with_fallback(
            direct_handler=handle_runner_run,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_run_stop(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Stop the running game (if any)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_stop

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["run", "stop"]

        return _run_with_fallback(
            direct_handler=handle_runner_stop,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_run_status(
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Check whether the game is running."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.runner_commands import handle_runner_status

        args = argparse.Namespace(project_root=project_root)
        cli_args = ["run", "status"]

        return _run_with_fallback(
            direct_handler=handle_runner_status,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Event tools
    # -----------------------------
    @mcp.tool()
    def gm_event_add(
        object: str,
        event: str,
        template: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Add an event to an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_add

        args = argparse.Namespace(object=object, event=event, template=template if template else None, project_root=project_root)
        cli_args = ["event", "add", object, event]
        if template:
            cli_args.extend(["--template", template])

        return _run_with_fallback(
            direct_handler=handle_event_add,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_event_remove(
        object: str,
        event: str,
        keep_file: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Remove an event from an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_remove

        # CLI uses --keep-file which sets delete_file=False
        args = argparse.Namespace(object=object, event=event, delete_file=(not keep_file), project_root=project_root)
        cli_args = ["event", "remove", object, event]
        if keep_file:
            cli_args.append("--keep-file")

        return _run_with_fallback(
            direct_handler=handle_event_remove,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_event_duplicate(
        object: str,
        source_event: str,
        target_num: int,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Duplicate an event within an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_duplicate

        args = argparse.Namespace(object=object, source_event=source_event, target_num=target_num, project_root=project_root)
        cli_args = ["event", "duplicate", object, source_event, str(target_num)]

        return _run_with_fallback(
            direct_handler=handle_event_duplicate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_event_list(
        object: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """List all events for an object."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_list

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "list", object]

        return _run_with_fallback(
            direct_handler=handle_event_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_event_validate(
        object: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Validate object events."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_validate

        args = argparse.Namespace(object=object, project_root=project_root)
        cli_args = ["event", "validate", object]

        return _run_with_fallback(
            direct_handler=handle_event_validate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_event_fix(
        object: str,
        safe_mode: bool = True,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Fix object event issues (safe_mode defaults true)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.event_commands import handle_event_fix

        args = argparse.Namespace(object=object, safe_mode=safe_mode, project_root=project_root)
        cli_args = ["event", "fix", object]
        if not safe_mode:
            cli_args.append("--no-safe-mode")

        return _run_with_fallback(
            direct_handler=handle_event_fix,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Workflow tools
    # -----------------------------
    @mcp.tool()
    def gm_workflow_duplicate(
        asset_path: str,
        new_name: str,
        yes: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Duplicate an asset (.yy path relative to project root)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_duplicate

        args = argparse.Namespace(asset_path=asset_path, new_name=new_name, yes=yes, project_root=project_root)
        cli_args = ["workflow", "duplicate", asset_path, new_name]
        if yes:
            cli_args.append("--yes")

        return _run_with_fallback(
            direct_handler=handle_workflow_duplicate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_workflow_rename(
        asset_path: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Rename an asset (.yy path relative to project root)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_rename

        args = argparse.Namespace(asset_path=asset_path, new_name=new_name, project_root=project_root)
        cli_args = ["workflow", "rename", asset_path, new_name]

        return _run_with_fallback(
            direct_handler=handle_workflow_rename,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_workflow_delete(
        asset_path: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Delete an asset by .yy path (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_delete

        args = argparse.Namespace(asset_path=asset_path, dry_run=dry_run, project_root=project_root)
        cli_args = ["workflow", "delete", asset_path]
        if dry_run:
            cli_args.append("--dry-run")

        return _run_with_fallback(
            direct_handler=handle_workflow_delete,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_workflow_swap_sprite(
        asset_path: str,
        png: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Replace a sprite's PNG source."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.workflow_commands import handle_workflow_swap_sprite

        args = argparse.Namespace(asset_path=asset_path, png=png, project_root=project_root)
        cli_args = ["workflow", "swap-sprite", asset_path, png]

        return _run_with_fallback(
            direct_handler=handle_workflow_swap_sprite,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    # -----------------------------
    # Room tools
    # -----------------------------
    @mcp.tool()
    def gm_room_ops_duplicate(
        source_room: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Duplicate an existing room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_duplicate

        args = argparse.Namespace(source_room=source_room, new_name=new_name, project_root=project_root)
        cli_args = ["room", "ops", "duplicate", source_room, new_name]

        return _run_with_fallback(
            direct_handler=handle_room_duplicate,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_ops_rename(
        room_name: str,
        new_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Rename an existing room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_rename

        args = argparse.Namespace(room_name=room_name, new_name=new_name, project_root=project_root)
        cli_args = ["room", "ops", "rename", room_name, new_name]

        return _run_with_fallback(
            direct_handler=handle_room_rename,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_ops_delete(
        room_name: str,
        dry_run: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Delete a room (supports dry-run)."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_delete

        args = argparse.Namespace(room_name=room_name, dry_run=dry_run, project_root=project_root)
        cli_args = ["room", "ops", "delete", room_name]
        if dry_run:
            cli_args.append("--dry-run")

        return _run_with_fallback(
            direct_handler=handle_room_delete,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_ops_list(
        verbose: bool = False,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """List rooms."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_list

        args = argparse.Namespace(verbose=verbose, project_root=project_root)
        cli_args = ["room", "ops", "list"]
        if verbose:
            cli_args.append("--verbose")

        return _run_with_fallback(
            direct_handler=handle_room_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_layer_add(
        room_name: str,
        layer_type: str,
        layer_name: str,
        depth: int = 0,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Add a layer to a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_add

        args = argparse.Namespace(room_name=room_name, layer_type=layer_type, layer_name=layer_name, depth=depth, project_root=project_root)
        cli_args = ["room", "layer", "add", room_name, layer_type, layer_name]

        return _run_with_fallback(
            direct_handler=handle_room_layer_add,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_layer_remove(
        room_name: str,
        layer_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Remove a layer from a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_remove

        args = argparse.Namespace(room_name=room_name, layer_name=layer_name, project_root=project_root)
        cli_args = ["room", "layer", "remove", room_name, layer_name]

        return _run_with_fallback(
            direct_handler=handle_room_layer_remove,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_layer_list(
        room_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """List layers in a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_layer_list

        args = argparse.Namespace(room_name=room_name, project_root=project_root)
        cli_args = ["room", "layer", "list", room_name]

        return _run_with_fallback(
            direct_handler=handle_room_layer_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_instance_add(
        room_name: str,
        object_name: str,
        x: float,
        y: float,
        layer: str = "",
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Add an object instance to a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_add

        args = argparse.Namespace(room_name=room_name, object_name=object_name, x=x, y=y, layer=layer if layer else None, project_root=project_root)
        cli_args = ["room", "instance", "add", room_name, object_name, str(x), str(y)]
        if layer:
            cli_args.extend(["--layer", layer])

        return _run_with_fallback(
            direct_handler=handle_room_instance_add,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_instance_remove(
        room_name: str,
        instance_id: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """Remove an instance from a room by instance id."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_remove

        args = argparse.Namespace(room_name=room_name, instance_id=instance_id, project_root=project_root)
        cli_args = ["room", "instance", "remove", room_name, instance_id]

        return _run_with_fallback(
            direct_handler=handle_room_instance_remove,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    @mcp.tool()
    def gm_room_instance_list(
        room_name: str,
        project_root: str = ".",
        prefer_cli: bool = False,
        output_mode: str = "full",
        tail_lines: int = 120,
        quiet: bool = False,
    ) -> Dict[str, Any]:
        """List instances in a room."""
        repo_root = _resolve_repo_root(project_root)
        _ensure_cli_on_sys_path(repo_root)
        from gms_helpers.commands.room_commands import handle_room_instance_list

        args = argparse.Namespace(room_name=room_name, project_root=project_root)
        cli_args = ["room", "instance", "list", room_name]

        return _run_with_fallback(
            direct_handler=handle_room_instance_list,
            direct_args=args,
            cli_args=cli_args,
            project_root=project_root,
            prefer_cli=prefer_cli,
            output_mode=output_mode,
            tail_lines=tail_lines,
            quiet=quiet,
        )

    return mcp


def main() -> int:
    try:
        server = build_server()
    except ModuleNotFoundError as e:
        sys.stderr.write(
            "MCP dependency is missing.\n"
            "Install it with:\n"
            f"  {sys.executable} -m pip install -U gms-mcp-tools\n"
        )
        sys.stderr.write(f"\nDetails: {e}\n")
        return 1

    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
