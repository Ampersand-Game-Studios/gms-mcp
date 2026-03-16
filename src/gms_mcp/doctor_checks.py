from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from .project_detection import find_yyp_name, resolve_project_directory
from .update_notifier import get_current_version, get_install_location
from .update_status import get_update_status


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_status(status: str) -> str:
    lowered = status.strip().lower()
    if lowered == "warn":
        return "warning"
    if lowered == "unknown":
        return "info"
    if lowered in {"ok", "warning", "error", "info"}:
        return lowered
    return "info"


def _severity_for_status(status: str, *, fatal: bool = False) -> str:
    normalized = _normalize_status(status)
    if normalized == "error":
        return "fatal" if fatal else "warning"
    if normalized == "warning":
        return "warning"
    return "info"


def _scope_for_health_check(check_id: str) -> str:
    if check_id in {"runtime", "license", "runtime_selection"}:
        return "runtime"
    if check_id in {"environment", "dependencies"}:
        return "environment"
    if check_id == "bridge":
        return "bridge"
    if check_id.startswith("client_"):
        return "client"
    return "project"


@dataclass
class DoctorCheck:
    id: str
    name: str
    scope: str
    status: str
    severity: str
    message: str
    details: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    recommendation: list[str] = field(default_factory=list)
    cached: bool = False
    checked_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorReport:
    checks: list[DoctorCheck]
    summary: str
    overall_status: str
    exit_code: int
    command: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        stats = {
            "total": len(self.checks),
            "ok": sum(1 for check in self.checks if check.status == "ok"),
            "warning": sum(1 for check in self.checks if check.status == "warning"),
            "error": sum(1 for check in self.checks if check.status == "error"),
            "info": sum(1 for check in self.checks if check.status == "info"),
        }
        return {
            "schema_version": "1.0.0",
            "generated_at": _utc_now_iso(),
            "ok": self.exit_code == 0,
            "summary": self.summary,
            "overall_status": self.overall_status,
            "exit_code": self.exit_code,
            "command": self.command,
            "stats": stats,
            "checks": [check.to_dict() for check in self.checks],
        }


def _build_package_check() -> DoctorCheck:
    version = get_current_version()
    return DoctorCheck(
        id="package",
        name="package",
        scope="global",
        status="ok",
        severity="info",
        message=f"gms-mcp {version} installed",
        metadata={
            "version": version,
            "python": sys.executable,
            "install_location": get_install_location(),
        },
    )


def _build_project_detection_check(*, project_root: str | None, required: bool) -> tuple[DoctorCheck, Path | None]:
    try:
        project_directory = resolve_project_directory(project_root)
        yyp_name = find_yyp_name(project_directory)
        return (
            DoctorCheck(
                id="project_detection",
                name="project",
                scope="project",
                status="ok",
                severity="info",
                message=f"GameMaker project detected: {yyp_name or 'unknown'}",
                metadata={
                    "project_directory": str(project_directory),
                    "yyp": yyp_name,
                },
            ),
            project_directory,
        )
    except FileNotFoundError as exc:
        status = "error" if required else "info"
        return (
            DoctorCheck(
                id="project_detection",
                name="project",
                scope="project",
                status=status,
                severity=_severity_for_status(status, fatal=required),
                message="No GameMaker project detected."
                if not required
                else f"GameMaker project not found: {exc}",
                recommendation=(
                    [
                        "Run from a workspace with a .yyp file.",
                        "Or pass --project-root to target the GameMaker project directory.",
                    ]
                    if required
                    else []
                ),
                metadata={"error": str(exc)},
            ),
            None,
        )


def _build_updates_check() -> DoctorCheck:
    update_status = get_update_status()
    status = _normalize_status(update_status.status)
    severity = "warning" if update_status.update_available else "info"
    return DoctorCheck(
        id="updates",
        name="updates",
        scope="global",
        status=status,
        severity=severity,
        message=update_status.message,
        metadata=update_status.to_dict(),
        recommendation=[f"Run: {update_status.upgrade_command}"] if update_status.update_available else [],
        cached=update_status.used_cache,
        checked_at=update_status.checked_at,
    )


def _build_health_checks(project_root: str) -> list[DoctorCheck]:
    from gms_helpers.health import gm_mcp_health

    result = gm_mcp_health(project_root)
    payload = result.data if isinstance(result.data, dict) else {}
    checks: list[DoctorCheck] = []
    for raw_check in payload.get("checks", []):
        if raw_check.get("id") == "project":
            continue
        raw_id = str(raw_check.get("id") or "health")
        raw_status = _normalize_status(str(raw_check.get("status") or "info"))
        details = raw_check.get("details")
        metadata = raw_check.get("data")
        checks.append(
            DoctorCheck(
                id=f"health_{raw_id}",
                name=raw_id,
                scope=_scope_for_health_check(raw_id),
                status=raw_status,
                severity=_severity_for_status(raw_status, fatal=raw_status == "error"),
                message=str(raw_check.get("summary") or raw_check.get("message") or raw_id),
                details=[str(detail) for detail in details] if isinstance(details, list) else [],
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        )
    return checks


def _build_runtime_selection_check(project_directory: Path) -> DoctorCheck:
    from gms_helpers.runtime_manager import RuntimeManager

    manager = RuntimeManager(project_directory)
    installed = manager.list_installed()
    active = manager.select()
    pinned = manager.get_pinned()
    verify = manager.verify()

    if active is None:
        return DoctorCheck(
            id="runtime_selection",
            name="runtime-selection",
            scope="runtime",
            status="error",
            severity="fatal",
            message="No GameMaker runtimes were discovered.",
            recommendation=["Install a GameMaker runtime through the IDE."],
            metadata={"count": 0, "pinned_version": pinned},
        )

    status = "ok" if verify.get("ok") else "error"
    details = [f"Installed runtimes: {len(installed)}"]
    if pinned:
        details.append(f"Pinned runtime: {pinned}")
    issues = verify.get("issues")
    if isinstance(issues, list):
        details.extend(str(issue) for issue in issues)

    return DoctorCheck(
        id="runtime_selection",
        name="runtime-selection",
        scope="runtime",
        status=status,
        severity=_severity_for_status(status, fatal=status == "error"),
        message=f"Active runtime: {active.version}",
        details=details,
        metadata={
            "count": len(installed),
            "active_version": active.version,
            "pinned_version": pinned,
            "verification": verify,
        },
        recommendation=["Verify the selected runtime in GameMaker and refresh runtimes."]
        if status == "error"
        else [],
    )


def _build_bridge_check(project_root: str) -> DoctorCheck:
    from gms_helpers.bridge_installer import get_bridge_status
    from gms_helpers.bridge_server import get_bridge_server

    try:
        install_status = get_bridge_status(project_root)
        server = get_bridge_server(project_root, create=False)
        server_status = server.get_status() if server else {"running": False, "connected": False, "log_count": 0}
    except Exception as exc:
        return DoctorCheck(
            id="bridge",
            name="bridge",
            scope="bridge",
            status="warning",
            severity="warning",
            message=f"Bridge status check failed: {exc}",
            metadata={"error": str(exc)},
        )

    installed = bool(install_status.get("installed"))
    running = bool(server_status.get("running"))
    connected = bool(server_status.get("connected"))
    log_count = int(server_status.get("log_count", 0))

    if connected:
        status = "ok"
        message = "Bridge installed and connected to a running game."
    elif installed and running:
        status = "info"
        message = "Bridge installed and server running, but no game is connected."
    elif installed:
        status = "info"
        message = "Bridge is installed for this project."
    else:
        status = "info"
        message = "Bridge is not installed for this project."

    details = [
        f"installed: {'yes' if installed else 'no'}",
        f"server_running: {'yes' if running else 'no'}",
        f"game_connected: {'yes' if connected else 'no'}",
        f"log_count: {log_count}",
    ]
    return DoctorCheck(
        id="bridge",
        name="bridge",
        scope="bridge",
        status=status,
        severity=_severity_for_status(status),
        message=message,
        details=details,
        metadata={"install_details": install_status, "server_status": server_status},
    )


def _build_codex_client_check(*, workspace_root: Path, server_name: str) -> DoctorCheck:
    from .install import _collect_codex_check_state

    state = _collect_codex_check_state(workspace_root=workspace_root, server_name=server_name)
    active_scope = state.get("active", {}).get("scope")
    active_path = state.get("active", {}).get("path")
    ready = bool(state.get("ready"))
    problems = [str(problem) for problem in state.get("problems", [])]

    if active_scope == "none":
        message = f"No Codex MCP entry named '{server_name}' was found."
        status = "warning"
    elif ready:
        message = f"Codex config is ready ({active_scope})."
        status = "ok"
    else:
        message = f"Codex config found but is not ready ({active_scope})."
        status = "warning"

    details = []
    if active_path:
        details.append(f"Active config: {active_path}")
    details.extend(problems)
    return DoctorCheck(
        id="client_codex",
        name="client-codex",
        scope="client",
        status=status,
        severity=_severity_for_status(status),
        message=message,
        details=details,
        metadata=state,
    )


def _build_claude_client_checks(*, workspace_root: Path, server_name: str) -> list[DoctorCheck]:
    from .install import _collect_client_check_state

    checks: list[DoctorCheck] = []
    states = [
        _collect_client_check_state(
            client="claude-code",
            scope="workspace",
            workspace_root=workspace_root,
            server_name=server_name,
            config_path_override=None,
        ),
        _collect_client_check_state(
            client="claude-desktop",
            scope="global",
            workspace_root=workspace_root,
            server_name=server_name,
            config_path_override=None,
        ),
    ]
    for state in states:
        ready = bool(state.readiness.ready)
        if state.readiness.not_applicable:
            status = "info"
            message = f"{state.client} config is not applicable for this scope."
        elif ready:
            status = "ok"
            message = f"{state.client} config is ready."
        elif state.entry is None:
            status = "warning"
            message = f"{state.client} config entry '{state.server_name}' was not found."
        else:
            status = "warning"
            message = f"{state.client} config found but is not ready."

        details = [f"Config path: {state.path}"]
        details.extend(str(problem) for problem in state.readiness.problems)
        checks.append(
            DoctorCheck(
                id=f"client_{state.client.replace('-', '_')}",
                name=f"client-{state.client}",
                scope="client",
                status=status,
                severity=_severity_for_status(status),
                message=message,
                details=details,
                metadata=state.as_dict(),
            )
        )
    return checks


def _build_client_checks(*, client: str, workspace_root: Path, server_name: str) -> list[DoctorCheck]:
    if client == "codex":
        return [_build_codex_client_check(workspace_root=workspace_root, server_name=server_name)]
    if client == "claude":
        return _build_claude_client_checks(workspace_root=workspace_root, server_name=server_name)
    raise ValueError(f"Unsupported client: {client}")


def _resolve_workspace_root(*, project_root: str | None, resolved_project: Path | None) -> Path:
    if project_root is not None:
        project_root_str = str(project_root).strip()
        if project_root_str and project_root_str != ".":
            candidate = Path(project_root_str).expanduser()
            if not candidate.is_absolute():
                candidate = (Path.cwd() / candidate).resolve()
            if candidate.is_file():
                candidate = candidate.parent

            markers = (".codex", ".cursor", ".vscode", ".claude-plugin", ".mcp.json")
            stop_at = candidate.parent
            for current in [candidate, *candidate.parents]:
                if current == stop_at:
                    break
                if any((current / marker).exists() for marker in markers):
                    return current
            return candidate

    return Path.cwd()


def _overall_status(checks: list[DoctorCheck]) -> str:
    if any(check.status == "error" for check in checks):
        return "error"
    if any(check.status == "warning" for check in checks):
        return "warning"
    if any(check.status == "ok" for check in checks):
        return "ok"
    return "info"


def _build_summary(checks: list[DoctorCheck]) -> str:
    errors = sum(1 for check in checks if check.status == "error")
    warnings = sum(1 for check in checks if check.status == "warning")
    if errors:
        return f"{errors} error(s), {warnings} warning(s)"
    if warnings:
        return f"{warnings} warning(s)"
    return "healthy"


def build_doctor_report(
    *,
    project: bool = False,
    full: bool = False,
    client: str | None = None,
    project_root: str | None = None,
    server_name: str = "gms",
) -> dict[str, Any]:
    checks: list[DoctorCheck] = []
    checks.append(_build_package_check())

    project_required = project or full or bool(project_root)
    project_check, resolved_project = _build_project_detection_check(
        project_root=project_root,
        required=project_required,
    )
    checks.append(project_check)
    checks.append(_build_updates_check())

    if resolved_project is not None and project_required:
        checks.extend(_build_health_checks(str(resolved_project)))
        if full:
            checks.append(_build_runtime_selection_check(resolved_project))
            checks.append(_build_bridge_check(str(resolved_project)))

    if client is not None:
        workspace_root = _resolve_workspace_root(project_root=project_root, resolved_project=resolved_project)
        checks.extend(
            _build_client_checks(
                client=client,
                workspace_root=workspace_root,
                server_name=server_name,
            )
        )

    overall_status = _overall_status(checks)
    report = DoctorReport(
        checks=checks,
        summary=_build_summary(checks),
        overall_status=overall_status,
        exit_code=2 if overall_status == "error" else 0,
        command={
            "project": project,
            "full": full,
            "client": client,
            "project_root": project_root,
            "server_name": server_name,
        },
    )
    return report.to_dict()
