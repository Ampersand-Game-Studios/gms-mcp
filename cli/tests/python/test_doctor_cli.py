import io
import json
import runpy
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from gms_mcp import doctor as doctor_module


class TestDoctorCLI(unittest.TestCase):
    def test_build_doctor_report_shape(self):
        with patch("gms_mcp.doctor_checks.get_current_version", return_value="1.0.0"), patch(
            "gms_mcp.doctor_checks.get_install_location", return_value="/tmp/site-packages"
        ), patch(
            "gms_mcp.doctor_checks.resolve_project_directory", side_effect=FileNotFoundError("no project")
        ), patch(
            "gms_mcp.doctor_checks.find_yyp_name", return_value="game.yyp"
        ), patch(
            "gms_mcp.doctor_checks.get_update_status",
            return_value=type(
                "UpdateStatusStub",
                (),
                {
                    "status": "warn",
                    "message": "A newer version is available",
                    "current_version": "1.0.0",
                    "latest_version": "1.1.0",
                    "source": "PyPI",
                    "url": "https://pypi.org/project/gms-mcp/",
                    "checked_at": "2026-03-16T00:00:00Z",
                    "used_cache": True,
                    "last_notified_at": None,
                    "notification_due": True,
                    "update_available": True,
                    "upgrade_command": "python3 -m pip install -U gms-mcp",
                    "to_dict": lambda self: {
                        "status": "warn",
                        "message": "A newer version is available",
                        "current_version": "1.0.0",
                        "latest_version": "1.1.0",
                        "source": "PyPI",
                        "url": "https://pypi.org/project/gms-mcp/",
                        "checked_at": "2026-03-16T00:00:00Z",
                        "used_cache": True,
                        "last_notified_at": None,
                        "notification_due": True,
                        "update_available": True,
                        "upgrade_command": "python3 -m pip install -U gms-mcp",
                    },
                },
            )(),
        ):
            report = doctor_module.build_doctor_report()

        self.assertTrue(report["ok"])
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertEqual(report["overall_status"], "warning")
        self.assertEqual(report["summary"], "1 warning(s)")
        self.assertEqual([check["name"] for check in report["checks"]], ["package", "project", "updates"])
        self.assertEqual(report["checks"][1]["message"], "No GameMaker project detected.")
        self.assertEqual(report["checks"][2]["metadata"]["upgrade_command"], "python3 -m pip install -U gms-mcp")

    def test_doctor_main_prints_json(self):
        report = {
            "schema_version": "1.0.0",
            "ok": True,
            "summary": "healthy",
            "overall_status": "ok",
            "exit_code": 0,
            "checks": [],
        }
        buffer = io.StringIO()
        with patch("gms_mcp.doctor.build_doctor_report", return_value=report), redirect_stdout(buffer):
            code = doctor_module.main(["--json"])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue()), report)

    def test_doctor_main_forwards_new_flags(self):
        report = {
            "schema_version": "1.0.0",
            "ok": False,
            "summary": "1 error(s), 0 warning(s)",
            "overall_status": "error",
            "exit_code": 2,
            "checks": [],
        }
        with patch("gms_mcp.doctor.build_doctor_report", return_value=report) as build_report:
            code = doctor_module.main(
                [
                    "--project",
                    "--full",
                    "--client",
                    "codex",
                    "--project-root",
                    "/tmp/project",
                    "--server-name",
                    "gms-app",
                    "--json",
                ]
            )

        self.assertEqual(code, 2)
        build_report.assert_called_once_with(
            project=True,
            full=True,
            client="codex",
            project_root="/tmp/project",
            server_name="gms-app",
        )

    def test_doctor_main_human_mode_uses_report_exit_code(self):
        report = {
            "schema_version": "1.0.0",
            "ok": False,
            "summary": "1 error(s), 0 warning(s)",
            "overall_status": "error",
            "exit_code": 2,
            "checks": [
                {
                    "name": "package",
                    "status": "ok",
                    "message": "pkg",
                    "details": [],
                    "metadata": {"python": "/usr/bin/python3", "install_location": "/tmp/site-packages"},
                },
                {
                    "name": "updates",
                    "status": "ok",
                    "message": "up to date",
                    "details": [],
                    "metadata": {"update_available": False},
                },
            ],
        }
        buffer = io.StringIO()
        with patch("gms_mcp.doctor.build_doctor_report", return_value=report), redirect_stdout(buffer):
            code = doctor_module.main([])

        self.assertEqual(code, 2)
        self.assertIn("overall-status: error", buffer.getvalue())

    def test_doctor_notify_prints_and_marks_when_due(self):
        update_status = type(
            "UpdateStatusStub",
            (),
            {
                "update_available": True,
                "notification_due": True,
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "source": "PyPI",
                "upgrade_command": "python3 -m pip install -U gms-mcp",
                "to_notification_record": lambda self: {
                    "status": "warn",
                    "latest_version": "1.1.0",
                    "source": "PyPI",
                    "url": "https://pypi.org/project/gms-mcp/",
                    "checked_at": "2026-03-16T00:00:00Z",
                    "current_version": "1.0.0",
                },
            },
        )()
        buffer = io.StringIO()
        with patch("gms_mcp.doctor.get_update_status", return_value=update_status), patch(
            "gms_mcp.doctor.mark_update_notified"
        ) as mark_notified, redirect_stdout(buffer):
            code = doctor_module.main(["--notify"])

        self.assertEqual(code, 0)
        self.assertIn("Update available via PyPI", buffer.getvalue())
        mark_notified.assert_called_once()

    def test_doctor_notify_is_silent_when_not_due(self):
        update_status = type(
            "UpdateStatusStub",
            (),
            {
                "update_available": True,
                "notification_due": False,
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "source": "PyPI",
                "upgrade_command": "python3 -m pip install -U gms-mcp",
                "to_notification_record": lambda self: {},
            },
        )()
        buffer = io.StringIO()
        with patch("gms_mcp.doctor.get_update_status", return_value=update_status), patch(
            "gms_mcp.doctor.mark_update_notified"
        ) as mark_notified, redirect_stdout(buffer):
            code = doctor_module.main(["--notify"])

        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "")
        mark_notified.assert_not_called()

    def test_module_entrypoint_dispatches_doctor(self):
        report = {
            "schema_version": "1.0.0",
            "ok": True,
            "summary": "healthy",
            "overall_status": "ok",
            "exit_code": 0,
            "checks": [],
        }
        buffer = io.StringIO()
        argv_backup = sys.argv[:]
        try:
            sys.argv = ["-m", "doctor", "--json"]
            with patch("gms_mcp.doctor.build_doctor_report", return_value=report), redirect_stdout(buffer):
                with self.assertRaises(SystemExit) as exc:
                    runpy.run_module("gms_mcp.cli", run_name="__main__")
        finally:
            sys.argv = argv_backup

        self.assertEqual(exc.exception.code, 0)
        self.assertEqual(json.loads(buffer.getvalue()), report)


if __name__ == "__main__":
    unittest.main()
