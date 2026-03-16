"""Health check and telemetry for GMS MCP."""
from __future__ import annotations

import platform
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .results import MaintenanceResult
from .runner import GameMakerRunner
from .utils import find_yyp, resolve_project_directory
from .exceptions import GMSError


@dataclass
class HealthCheck:
    id: str
    status: str
    summary: str
    details: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def render_lines(self) -> List[str]:
        lines = [f"[{self.status.upper()}] {self.summary}"]
        lines.extend(f"[INFO] {detail}" for detail in self.details)
        return lines


@dataclass
class HealthReport:
    checks: List[HealthCheck] = field(default_factory=list)

    @property
    def issues_found(self) -> int:
        return sum(1 for check in self.checks if check.status == "error")

    @property
    def success(self) -> bool:
        return self.issues_found == 0

    @property
    def message(self) -> str:
        if self.success:
            return "Health check passed!"
        return f"Health check found {self.issues_found} issue(s)."

    def flatten_details(self) -> List[str]:
        lines: List[str] = []
        for check in self.checks:
            lines.extend(check.render_lines())
        return lines

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.success,
            "message": self.message,
            "issues_found": self.issues_found,
            "checks": [asdict(check) for check in self.checks],
        }


def gm_mcp_health(project_root: Optional[str] = None) -> MaintenanceResult:
    """Perform a structured health check of the GameMaker development environment."""
    report = HealthReport()

    try:
        resolved_root = resolve_project_directory(project_root)
        yyp_path = find_yyp(resolved_root)
        report.checks.append(
            HealthCheck(
                id="project",
                status="ok",
                summary=f"Project found: {yyp_path.name}",
                details=[f"Project root: {resolved_root}"],
                data={"project_root": str(resolved_root), "yyp": yyp_path.name},
            )
        )
    except Exception as exc:
        resolved_root = Path(project_root) if project_root else Path.cwd()
        report.checks.append(
            HealthCheck(
                id="project",
                status="error",
                summary=f"Project not found or invalid: {exc}",
                data={"project_root": str(resolved_root)},
            )
        )

    runner = GameMakerRunner(resolved_root)
    igor_path = runner.find_gamemaker_runtime()
    if igor_path:
        report.checks.append(
            HealthCheck(
                id="runtime",
                status="ok",
                summary=f"Igor found: {igor_path}",
                details=[f"Runtime: {runner.runtime_path.name if runner.runtime_path else 'Unknown'}"],
                data={
                    "igor_path": str(igor_path),
                    "runtime": runner.runtime_path.name if runner.runtime_path else None,
                },
            )
        )
    else:
        report.checks.append(
            HealthCheck(
                id="runtime",
                status="error",
                summary="GameMaker runtime or Igor not found.",
                details=["Ensure GameMaker is installed and runtimes are downloaded."],
            )
        )

    license_file = runner.find_license_file()
    if license_file:
        report.checks.append(
            HealthCheck(
                id="license",
                status="ok",
                summary=f"GameMaker license found: {license_file}",
                data={"license_file": str(license_file)},
            )
        )
    else:
        report.checks.append(
            HealthCheck(
                id="license",
                status="error",
                summary="GameMaker license file not found.",
                details=["Ensure you are logged into GameMaker IDE."],
            )
        )

    report.checks.append(
        HealthCheck(
            id="environment",
            status="info",
            summary="Environment details captured.",
            details=[
                f"OS: {platform.system()} {platform.release()}",
                f"Python: {sys.version.split()[0]} ({sys.executable})",
            ],
            data={
                "os": f"{platform.system()} {platform.release()}",
                "python_version": sys.version.split()[0],
                "python_executable": sys.executable,
            },
        )
    )

    dependencies = ["mcp", "fastmcp", "pathlib", "colorama", "tqdm"]
    found_deps: List[str] = []
    missing_deps: List[str] = []
    for dep in dependencies:
        try:
            __import__(dep)
            found_deps.append(dep)
        except ImportError:
            missing_deps.append(dep)

    if missing_deps:
        report.checks.append(
            HealthCheck(
                id="dependencies",
                status="error",
                summary=f"Missing dependencies: {', '.join(missing_deps)}",
                details=["Run 'pip install -r src/gms_mcp/requirements.txt' to fix."],
                data={"found": found_deps, "missing": missing_deps},
            )
        )
    else:
        report.checks.append(
            HealthCheck(
                id="dependencies",
                status="ok",
                summary="Dependencies available.",
                details=[f"Dependency found: {dep}" for dep in found_deps],
                data={"found": found_deps, "missing": []},
            )
        )

    return MaintenanceResult(
        success=report.success,
        message=report.message,
        issues_found=report.issues_found,
        issues_fixed=0,
        details=report.flatten_details(),
        data=report.to_dict(),
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
