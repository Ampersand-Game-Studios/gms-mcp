"""Health check and telemetry for GMS MCP."""
import os
import sys
import platform
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from .results import MaintenanceResult
from .runner import GameMakerRunner
from .utils import find_yyp, resolve_project_directory
from .exceptions import GMSError

def gm_mcp_health(project_root: Optional[str] = None) -> MaintenanceResult:
    """
    Perform a comprehensive health check of the GameMaker development environment.
    
    Verifies:
    1. Project validity (.yyp, directory structure)
    2. GameMaker Runtimes & Igor.exe
    3. GameMaker License
    4. Python environment & dependencies
    """
    issues_found = 0
    details = []
    
    # 1. Project Check
    try:
        resolved_root = resolve_project_directory(project_root)
        yyp_path = find_yyp(resolved_root)
        details.append(f"[OK] Project found: {yyp_path.name}")
        details.append(f"[INFO] Project root: {resolved_root}")
    except Exception as e:
        issues_found += 1
        details.append(f"[ERROR] Project not found or invalid: {e}")
        resolved_root = Path(project_root) if project_root else Path.cwd()

    # 2. Runner & Runtimes Check
    runner = GameMakerRunner(resolved_root)
    igor_path = runner.find_gamemaker_runtime()
    if igor_path:
        details.append(f"[OK] Igor.exe found: {igor_path}")
        details.append(f"[INFO] Runtime: {runner.runtime_path.name if runner.runtime_path else 'Unknown'}")
    else:
        issues_found += 1
        details.append("[ERROR] GameMaker runtime or Igor.exe not found.")
        details.append("[INFO] Ensure GameMaker is installed and runtimes are downloaded.")

    # 3. License Check
    license_file = runner.find_license_file()
    if license_file:
        details.append(f"[OK] GameMaker license found: {license_file}")
    else:
        issues_found += 1
        details.append("[ERROR] GameMaker license file not found.")
        details.append("[INFO] Ensure you are logged into GameMaker IDE.")

    # 4. Environment Check
    details.append(f"[INFO] OS: {platform.system()} {platform.release()}")
    details.append(f"[INFO] Python: {sys.version.split()[0]} ({sys.executable})")
    
    # Check key dependencies
    dependencies = ["mcp", "fastmcp", "pathlib", "colorama", "tqdm"]
    missing_deps = []
    for dep in dependencies:
        try:
            __import__(dep)
            details.append(f"[OK] Dependency found: {dep}")
        except ImportError:
            missing_deps.append(dep)
            
    if missing_deps:
        issues_found += 1
        details.append(f"[ERROR] Missing dependencies: {', '.join(missing_deps)}")
        details.append("[INFO] Run 'pip install -r src/gms_mcp/requirements.txt' to fix.")

    success = issues_found == 0
    message = "Health check passed!" if success else f"Health check found {issues_found} issue(s)."
    
    return MaintenanceResult(
        success=success,
        message=message,
        issues_found=issues_found,
        issues_fixed=0,
        details=details
    )

if __name__ == "__main__":
    try:
        result = gm_mcp_health()
        for detail in result.details:
            print(detail)
        sys.exit(0 if result.success else 1)
    except GMSError as e:
        print(f"[ERROR] {e.message}")
        sys.exit(e.exit_code)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)
