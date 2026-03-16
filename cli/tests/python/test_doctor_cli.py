import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from gms_mcp import doctor as doctor_module


class TestDoctorCLI(unittest.TestCase):
    def test_build_doctor_report_shape(self):
        with patch("gms_mcp.doctor.get_current_version", return_value="1.0.0"), patch(
            "gms_mcp.doctor.get_install_location", return_value="/tmp/site-packages"
        ), patch(
            "gms_mcp.doctor.check_for_updates",
            return_value={
                "status": "warn",
                "message": "A newer version is available",
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "source": "PyPI",
                "checked_at": "2026-03-16T00:00:00Z",
                "used_cache": True,
                "notification_due": True,
                "upgrade_command": "python3 -m pip install -U gms-mcp",
                "url": "https://pypi.org/project/gms-mcp/",
            },
        ):
            report = doctor_module.build_doctor_report()

        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"], "update available")
        self.assertEqual(report["checks"][0]["name"], "package")
        self.assertEqual(report["checks"][1]["name"], "updates")
        self.assertEqual(report["checks"][1]["details"]["upgrade_command"], "python3 -m pip install -U gms-mcp")

    def test_doctor_main_prints_json(self):
        report = {"ok": True, "summary": "up to date", "checks": []}
        buffer = io.StringIO()
        with patch("gms_mcp.doctor.build_doctor_report", return_value=report), redirect_stdout(buffer):
            code = doctor_module.main(["--json"])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue()), report)

    def test_doctor_notify_prints_and_marks_when_due(self):
        report = {
            "ok": True,
            "summary": "update available",
            "checks": [
                {"name": "package", "status": "ok", "message": "pkg", "details": {}},
                {
                    "name": "updates",
                    "status": "warn",
                    "message": "A newer version is available",
                    "details": {
                        "current_version": "1.0.0",
                        "latest_version": "1.1.0",
                        "source": "PyPI",
                        "checked_at": "2026-03-16T00:00:00Z",
                        "notification_due": True,
                        "upgrade_command": "python3 -m pip install -U gms-mcp",
                        "url": "https://pypi.org/project/gms-mcp/",
                    },
                },
            ],
        }
        buffer = io.StringIO()
        with patch("gms_mcp.doctor.build_doctor_report", return_value=report), patch(
            "gms_mcp.doctor.mark_update_notified"
        ) as mark_notified, redirect_stdout(buffer):
            code = doctor_module.main(["--notify"])

        self.assertEqual(code, 0)
        self.assertIn("Update available via PyPI", buffer.getvalue())
        mark_notified.assert_called_once()

    def test_doctor_notify_is_silent_when_not_due(self):
        report = {
            "ok": True,
            "summary": "update available",
            "checks": [
                {"name": "package", "status": "ok", "message": "pkg", "details": {}},
                {
                    "name": "updates",
                    "status": "warn",
                    "message": "A newer version is available",
                    "details": {
                        "current_version": "1.0.0",
                        "latest_version": "1.1.0",
                        "source": "PyPI",
                        "checked_at": "2026-03-16T00:00:00Z",
                        "notification_due": False,
                        "upgrade_command": "python3 -m pip install -U gms-mcp",
                    },
                },
            ],
        }
        buffer = io.StringIO()
        with patch("gms_mcp.doctor.build_doctor_report", return_value=report), patch(
            "gms_mcp.doctor.mark_update_notified"
        ) as mark_notified, redirect_stdout(buffer):
            code = doctor_module.main(["--notify"])

        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "")
        mark_notified.assert_not_called()


if __name__ == "__main__":
    unittest.main()
