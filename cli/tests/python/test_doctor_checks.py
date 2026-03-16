import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gms_mcp import doctor_checks as doctor_checks_module


def _check(
    *,
    check_id: str,
    name: str,
    status: str = "ok",
    scope: str = "global",
    message: str | None = None,
) -> doctor_checks_module.DoctorCheck:
    return doctor_checks_module.DoctorCheck(
        id=check_id,
        name=name,
        scope=scope,
        status=status,
        severity=doctor_checks_module._severity_for_status(status, fatal=status == "error"),
        message=message or f"{name} {status}",
    )


class TestDoctorChecks(unittest.TestCase):
    def test_build_doctor_report_project_mode_includes_health_checks(self):
        with patch(
            "gms_mcp.doctor_checks._build_package_check",
            return_value=_check(check_id="package", name="package"),
        ), patch(
            "gms_mcp.doctor_checks._build_project_detection_check",
            return_value=(_check(check_id="project_detection", name="project"), Path("/tmp/project")),
        ), patch(
            "gms_mcp.doctor_checks._build_updates_check",
            return_value=_check(check_id="updates", name="updates"),
        ), patch(
            "gms_mcp.doctor_checks._build_health_checks",
            return_value=[
                _check(check_id="health_runtime", name="runtime"),
                _check(check_id="health_license", name="license", status="error"),
            ],
        ):
            report = doctor_checks_module.build_doctor_report(project=True)

        self.assertEqual([check["name"] for check in report["checks"]], ["package", "project", "updates", "runtime", "license"])
        self.assertEqual(report["overall_status"], "error")
        self.assertEqual(report["exit_code"], 2)
        self.assertEqual(report["command"]["project"], True)

    def test_build_doctor_report_full_mode_adds_runtime_and_bridge(self):
        with patch(
            "gms_mcp.doctor_checks._build_package_check",
            return_value=_check(check_id="package", name="package"),
        ), patch(
            "gms_mcp.doctor_checks._build_project_detection_check",
            return_value=(_check(check_id="project_detection", name="project"), Path("/tmp/project")),
        ), patch(
            "gms_mcp.doctor_checks._build_updates_check",
            return_value=_check(check_id="updates", name="updates", status="warning"),
        ), patch(
            "gms_mcp.doctor_checks._build_health_checks",
            return_value=[_check(check_id="health_runtime", name="runtime")],
        ), patch(
            "gms_mcp.doctor_checks._build_runtime_selection_check",
            return_value=_check(check_id="runtime_selection", name="runtime-selection"),
        ), patch(
            "gms_mcp.doctor_checks._build_bridge_check",
            return_value=_check(check_id="bridge", name="bridge", status="info"),
        ):
            report = doctor_checks_module.build_doctor_report(project=True, full=True)

        self.assertEqual(
            [check["name"] for check in report["checks"]],
            ["package", "project", "updates", "runtime", "runtime-selection", "bridge"],
        )
        self.assertEqual(report["overall_status"], "warning")
        self.assertEqual(report["summary"], "1 warning(s)")
        self.assertEqual(report["command"]["full"], True)

    def test_build_doctor_report_client_mode_adds_client_checks(self):
        with patch(
            "gms_mcp.doctor_checks._build_package_check",
            return_value=_check(check_id="package", name="package"),
        ), patch(
            "gms_mcp.doctor_checks._build_project_detection_check",
            return_value=(_check(check_id="project_detection", name="project", status="info"), None),
        ), patch(
            "gms_mcp.doctor_checks._build_updates_check",
            return_value=_check(check_id="updates", name="updates"),
        ), patch(
            "gms_mcp.doctor_checks._build_client_checks",
            return_value=[_check(check_id="client_codex", name="client-codex", scope="client")],
        ):
            report = doctor_checks_module.build_doctor_report(client="codex", server_name="gms-app")

        self.assertEqual([check["name"] for check in report["checks"]], ["package", "project", "updates", "client-codex"])
        self.assertEqual(report["command"]["client"], "codex")
        self.assertEqual(report["command"]["server_name"], "gms-app")
        self.assertEqual(report["exit_code"], 0)

    def test_build_doctor_report_client_mode_supports_claude(self):
        with patch(
            "gms_mcp.doctor_checks._build_package_check",
            return_value=_check(check_id="package", name="package"),
        ), patch(
            "gms_mcp.doctor_checks._build_project_detection_check",
            return_value=(_check(check_id="project_detection", name="project", status="info"), None),
        ), patch(
            "gms_mcp.doctor_checks._build_updates_check",
            return_value=_check(check_id="updates", name="updates"),
        ), patch(
            "gms_mcp.doctor_checks._build_client_checks",
            return_value=[
                _check(check_id="client_claude_code", name="client-claude-code", scope="client"),
                _check(check_id="client_claude_desktop", name="client-claude-desktop", scope="client", status="warning"),
            ],
        ):
            report = doctor_checks_module.build_doctor_report(client="claude")

        self.assertEqual(
            [check["name"] for check in report["checks"]],
            ["package", "project", "updates", "client-claude-code", "client-claude-desktop"],
        )
        self.assertEqual(report["command"]["client"], "claude")
        self.assertEqual(report["overall_status"], "warning")

    def test_build_doctor_report_client_mode_uses_requested_project_root_for_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            with patch(
                "gms_mcp.doctor_checks._build_package_check",
                return_value=_check(check_id="package", name="package"),
            ), patch(
                "gms_mcp.doctor_checks._build_project_detection_check",
                return_value=(_check(check_id="project_detection", name="project"), workspace_root / "gamemaker"),
            ), patch(
                "gms_mcp.doctor_checks._build_updates_check",
                return_value=_check(check_id="updates", name="updates"),
            ), patch(
                "gms_mcp.doctor_checks._build_client_checks",
                return_value=[_check(check_id="client_codex", name="client-codex", scope="client")],
            ) as build_client_checks:
                doctor_checks_module.build_doctor_report(client="codex", project_root=str(workspace_root))

        build_client_checks.assert_called_once_with(
            client="codex",
            workspace_root=workspace_root,
            server_name="gms",
        )

    def test_build_doctor_report_client_mode_defaults_to_cwd_workspace(self):
        with patch(
            "gms_mcp.doctor_checks._build_package_check",
            return_value=_check(check_id="package", name="package"),
        ), patch(
            "gms_mcp.doctor_checks._build_project_detection_check",
            return_value=(_check(check_id="project_detection", name="project"), Path("/tmp/workspace/gamemaker")),
        ), patch(
            "gms_mcp.doctor_checks._build_updates_check",
            return_value=_check(check_id="updates", name="updates"),
        ), patch(
            "gms_mcp.doctor_checks._build_client_checks",
            return_value=[_check(check_id="client_codex", name="client-codex", scope="client")],
        ) as build_client_checks, patch("gms_mcp.doctor_checks.Path.cwd", return_value=Path("/tmp/current-workspace")):
            doctor_checks_module.build_doctor_report(client="codex")

        build_client_checks.assert_called_once_with(
            client="codex",
            workspace_root=Path("/tmp/current-workspace"),
            server_name="gms",
        )

    def test_resolve_workspace_root_does_not_climb_outside_explicit_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            repo = home / "repo"
            project = repo / "gamemaker"
            project.mkdir(parents=True)
            (home / ".codex").mkdir()

            resolved = doctor_checks_module._resolve_workspace_root(
                project_root=str(project),
                resolved_project=project,
            )

        self.assertEqual(resolved, project)


if __name__ == "__main__":
    unittest.main()
