"""Runner command implementations."""

from pathlib import Path
from typing import Dict, Any, Union

from ..runner import GameMakerRunner


def handle_runner_compile(args) -> bool:
    """Handle project compilation."""
    try:
        # Use current working directory if no project root specified
        if hasattr(args, 'project_root') and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()
        
        print(f"[BUILD] Compiling GameMaker project in: {project_root}")
        
        runtime_version = getattr(args, 'runtime_version', None)
        runner = GameMakerRunner(project_root, runtime_version=runtime_version)
        
        platform = getattr(args, 'platform', 'Windows')
        runtime = getattr(args, 'runtime', 'VM')
        
        success = runner.compile_project(platform, runtime)
        
        if success:
            print("[SUCCESS] Compilation completed successfully!")
        else:
            print("[ERROR] Compilation failed!")
            
        return success
        
    except Exception as e:
        print(f"[ERROR] Error during compilation: {e}")
        return False


def handle_runner_run(args) -> Union[bool, Dict[str, Any]]:
    """
    Handle project execution.
    
    Returns:
        If background=False: bool (True if game exited successfully)
        If background=True: dict with session info (pid, run_id, etc.)
    """
    try:
        # Use current working directory if no project root specified
        if hasattr(args, 'project_root') and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()
        
        print(f"[START] Running GameMaker project in: {project_root}")
        
        runtime_version = getattr(args, 'runtime_version', None)
        runner = GameMakerRunner(project_root, runtime_version=runtime_version)
        
        platform = getattr(args, 'platform', 'Windows')
        runtime = getattr(args, 'runtime', 'VM')
        background = getattr(args, 'background', False)
        output_location = getattr(args, 'output_location', 'temp')
        
        result = runner.run_project_direct(platform, runtime, background, output_location)
        
        return result
        
    except Exception as e:
        print(f"[ERROR] Error during execution: {e}")
        if getattr(args, 'background', False):
            return {"ok": False, "error": str(e), "message": f"Failed to start game: {e}"}
        return False


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
        if hasattr(args, 'project_root') and args.project_root:
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
        
        return result
        
    except Exception as e:
        print(f"[ERROR] Error stopping game: {e}")
        return {"ok": False, "error": str(e), "message": f"Error stopping game: {e}"}


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
        if hasattr(args, 'project_root') and args.project_root:
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
        
        return status
        
    except Exception as e:
        print(f"[ERROR] Error checking status: {e}")
        return {"ok": False, "error": str(e), "message": f"Error checking status: {e}"}
