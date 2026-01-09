#!/usr/bin/env python3
"""
Run Session Management for GameMaker MCP

Provides persistent session tracking for running GameMaker games.
Sessions are stored on disk so they survive:
- Multiple MCP tool calls
- MCP server restarts
- Cursor restarts

This solves the problem where gm_run_stop/gm_run_status couldn't find
the game process because the GameMakerRunner instance was recreated.
"""

import json
import os
import time
import subprocess
import platform
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


@dataclass
class RunSession:
    """Represents a running game session."""
    run_id: str
    pid: int
    exe_path: str
    project_root: str
    started_at: str
    platform_target: str = "Windows"
    runtime_type: str = "VM"
    log_file: Optional[str] = None
    bridge_port: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunSession":
        return cls(**data)


class RunSessionManager:
    """
    Manages persistent run sessions for GameMaker games.
    
    Session data is stored in .gms_mcp/sessions/ relative to project root.
    """
    
    SESSIONS_DIR = ".gms_mcp/sessions"
    CURRENT_SESSION_FILE = "current.json"
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.sessions_dir = self.project_root / self.SESSIONS_DIR
        
    def _ensure_sessions_dir(self) -> Path:
        """Ensure the sessions directory exists."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        return self.sessions_dir
    
    def _current_session_path(self) -> Path:
        """Get path to current session file."""
        return self.sessions_dir / self.CURRENT_SESSION_FILE
    
    def _generate_run_id(self) -> str:
        """Generate a unique run ID."""
        # time.time_ns() is monotonic enough for our purposes and avoids collisions when
        # multiple sessions are created within the same millisecond.
        return f"run_{time.time_ns()}"
    
    def create_session(
        self,
        pid: int,
        exe_path: str,
        platform_target: str = "Windows",
        runtime_type: str = "VM",
        log_file: Optional[str] = None,
        bridge_port: Optional[int] = None,
    ) -> RunSession:
        """
        Create and persist a new run session.
        
        Args:
            pid: Process ID of the running game
            exe_path: Path to the game executable
            platform_target: Target platform
            runtime_type: VM or YYC
            log_file: Optional path to log file
            bridge_port: Optional bridge server port
            
        Returns:
            The created RunSession
        """
        self._ensure_sessions_dir()
        
        session = RunSession(
            run_id=self._generate_run_id(),
            pid=pid,
            exe_path=str(exe_path),
            project_root=str(self.project_root),
            started_at=datetime.now().isoformat(),
            platform_target=platform_target,
            runtime_type=runtime_type,
            log_file=log_file,
            bridge_port=bridge_port,
        )
        
        # Write session to disk
        session_path = self._current_session_path()
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)
        
        print(f"[SESSION] Created session {session.run_id} (PID: {pid})")
        return session
    
    def get_current_session(self) -> Optional[RunSession]:
        """
        Get the current run session, if any.
        
        Returns:
            RunSession if one exists, None otherwise
        """
        session_path = self._current_session_path()
        
        if not session_path.exists():
            return None
        
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RunSession.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[SESSION] Failed to read session file: {e}")
            return None
    
    def clear_session(self) -> bool:
        """
        Clear the current session file.
        
        Returns:
            True if cleared, False if no session existed
        """
        session_path = self._current_session_path()
        
        if session_path.exists():
            session_path.unlink()
            print("[SESSION] Cleared current session")
            return True
        return False
    
    def is_process_alive(self, pid: int) -> bool:
        """
        Check if a process with the given PID is still running.
        
        Args:
            pid: Process ID to check
            
        Returns:
            True if process is running, False otherwise
        """
        try:
            if platform.system() == "Windows":
                # On Windows, use tasklist to check if PID exists
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                # If PID is found, tasklist returns a line with the PID
                return str(pid) in result.stdout
            else:
                # On Unix, send signal 0 to check if process exists
                os.kill(pid, 0)
                return True
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            return False
        except OSError:
            # Process doesn't exist
            return False
        except Exception:
            return False
    
    def kill_process(self, pid: int, force: bool = False) -> bool:
        """
        Kill a process by PID.
        
        Args:
            pid: Process ID to kill
            force: If True, force kill immediately
            
        Returns:
            True if process was killed, False otherwise
        """
        try:
            if platform.system() == "Windows":
                # Use taskkill on Windows
                args = ["taskkill"]
                if force:
                    args.append("/F")
                args.extend(["/PID", str(pid), "/T"])  # /T kills child processes too
                
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                return result.returncode == 0
            else:
                # On Unix, use signals
                import signal
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)
                return True
        except Exception as e:
            print(f"[SESSION] Failed to kill process {pid}: {e}")
            return False
    
    def get_session_status(self) -> Dict[str, Any]:
        """
        Get the status of the current session.
        
        Returns:
            Dict with session info and running status
        """
        session = self.get_current_session()
        
        if not session:
            return {
                "has_session": False,
                "running": False,
                "message": "No game session found",
            }
        
        is_running = self.is_process_alive(session.pid)
        
        return {
            "has_session": True,
            "running": is_running,
            "run_id": session.run_id,
            "pid": session.pid,
            "exe_path": session.exe_path,
            "started_at": session.started_at,
            "platform": session.platform_target,
            "runtime": session.runtime_type,
            "log_file": session.log_file,
            "bridge_port": session.bridge_port,
            "message": f"Game is {'running' if is_running else 'not running'} (PID: {session.pid})",
        }
    
    def stop_game(self) -> Dict[str, Any]:
        """
        Stop the currently running game.
        
        Returns:
            Dict with result of stop operation
        """
        session = self.get_current_session()
        
        if not session:
            return {
                "ok": False,
                "message": "No game session found",
            }
        
        pid = session.pid
        
        if not self.is_process_alive(pid):
            # Process already dead, just clean up session
            self.clear_session()
            return {
                "ok": True,
                "message": f"Game (PID: {pid}) was already stopped. Cleaned up session.",
            }
        
        # Try graceful termination first
        print(f"[STOP] Stopping game (PID: {pid})...")
        
        if self.kill_process(pid, force=False):
            # Wait a moment for graceful shutdown
            time.sleep(0.5)
            
            if not self.is_process_alive(pid):
                self.clear_session()
                return {
                    "ok": True,
                    "message": f"Game (PID: {pid}) stopped successfully.",
                }
        
        # Force kill if still running
        print(f"[STOP] Forcing kill of game (PID: {pid})...")
        if self.kill_process(pid, force=True):
            time.sleep(0.3)
            self.clear_session()
            return {
                "ok": True,
                "message": f"Game (PID: {pid}) force-killed.",
            }
        
        return {
            "ok": False,
            "message": f"Failed to stop game (PID: {pid}). Process may still be running.",
        }


def get_session_manager(project_root: str = ".") -> RunSessionManager:
    """
    Get a RunSessionManager for the given project root.
    
    Args:
        project_root: Path to project root (default: current directory)
        
    Returns:
        RunSessionManager instance
    """
    return RunSessionManager(Path(project_root).resolve())
