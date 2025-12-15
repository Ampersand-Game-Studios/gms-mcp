"""Runner command implementations."""

from pathlib import Path

from ..runner import GameMakerRunner


def handle_runner_compile(args):
    """Handle project compilation."""
    try:
        # Use current working directory if no project root specified
        if hasattr(args, 'project_root') and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()
        
        print(f"🔨 Compiling GameMaker project in: {project_root}")
        
        runner = GameMakerRunner(project_root)
        
        platform = getattr(args, 'platform', 'Windows')
        runtime = getattr(args, 'runtime', 'VM')
        
        success = runner.compile_project(platform, runtime)
        
        if success:
            print("[SUCCESS] Compilation completed successfully!")
        else:
            print("💥 Compilation failed!")
            
        return success
        
    except Exception as e:
        print(f"[ERROR] Error during compilation: {e}")
        return False


def handle_runner_run(args):
    """Handle project execution."""
    try:
        # Use current working directory if no project root specified
        if hasattr(args, 'project_root') and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()
        
        print(f"[START] Running GameMaker project in: {project_root}")
        
        runner = GameMakerRunner(project_root)
        
        platform = getattr(args, 'platform', 'Windows')
        runtime = getattr(args, 'runtime', 'VM')
        background = getattr(args, 'background', False)
        output_location = getattr(args, 'output_location', 'temp')
        
        success = runner.run_project_direct(platform, runtime, background, output_location)
        
        return success
        
    except Exception as e:
        print(f"[ERROR] Error during execution: {e}")
        return False


def handle_runner_stop(args):
    """Handle stopping the running game."""
    try:
        # Use current working directory if no project root specified
        if hasattr(args, 'project_root') and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()
        
        print(f"[STOP] Stopping GameMaker project in: {project_root}")
        
        runner = GameMakerRunner(project_root)
        
        success = runner.stop_game()
        
        return success
        
    except Exception as e:
        print(f"[ERROR] Error stopping game: {e}")
        return False


def handle_runner_status(args):
    """Check if game is currently running."""
    try:
        # Use current working directory if no project root specified
        if hasattr(args, 'project_root') and args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = Path.cwd()
        
        runner = GameMakerRunner(project_root)
        
        if runner.is_game_running():
            print("🎮 Game is currently running")
        else:
            print("💤 No game currently running")
            
        return True
        
    except Exception as e:
        print(f"[ERROR] Error checking status: {e}")
        return False 
