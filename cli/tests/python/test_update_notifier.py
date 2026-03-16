import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gms_mcp.update_notifier import check_for_updates, mark_update_notified


class TestUpdateNotifier(unittest.TestCase):
    def test_update_available_pypi(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "gms_mcp.update_notifier.Path.home", return_value=Path(tmpdir)
        ), patch("gms_mcp.update_notifier.get_current_version", return_value="1.0.0"), patch(
            "gms_mcp.update_notifier.get_upgrade_command", return_value="pipx upgrade gms-mcp"
        ), patch("gms_mcp.update_notifier._utc_now", return_value=1_000.0), patch(
            "gms_mcp.update_notifier.get_latest_version_pypi", return_value="1.1.0"
        ) as pypi, patch(
            "gms_mcp.update_notifier.get_latest_version_github"
        ) as github:
            result = check_for_updates(force_refresh=True)

        self.assertTrue(result["update_available"])
        self.assertEqual(result["status"], "warn")
        self.assertEqual(result["latest_version"], "1.1.0")
        self.assertEqual(result["source"], "PyPI")
        self.assertFalse(result["used_cache"])
        self.assertTrue(result["notification_due"])
        self.assertEqual(result["upgrade_command"], "pipx upgrade gms-mcp")
        pypi.assert_called_once()
        github.assert_not_called()

    def test_update_available_github_after_pypi_no_change(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "gms_mcp.update_notifier.Path.home", return_value=Path(tmpdir)
        ), patch("gms_mcp.update_notifier.get_current_version", return_value="1.0.0"), patch(
            "gms_mcp.update_notifier._utc_now", return_value=1_000.0
        ), patch("gms_mcp.update_notifier.get_latest_version_pypi", return_value="1.0.0"), patch(
            "gms_mcp.update_notifier.get_latest_version_github", return_value="1.2.0"
        ):
            result = check_for_updates(force_refresh=True)

        self.assertTrue(result["update_available"])
        self.assertEqual(result["status"], "warn")
        self.assertEqual(result["latest_version"], "1.2.0")
        self.assertEqual(result["source"], "GitHub")

    def test_no_update_needed(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "gms_mcp.update_notifier.Path.home", return_value=Path(tmpdir)
        ), patch("gms_mcp.update_notifier.get_current_version", return_value="1.1.0"), patch(
            "gms_mcp.update_notifier._utc_now", return_value=1_000.0
        ), patch("gms_mcp.update_notifier.get_latest_version_pypi", return_value="1.1.0"), patch(
            "gms_mcp.update_notifier.get_latest_version_github", return_value="1.1.0"
        ):
            result = check_for_updates(force_refresh=True)

        self.assertFalse(result["update_available"])
        self.assertEqual(result["status"], "ok")
        self.assertIn("latest version", result["message"])

    def test_refresh_failure_uses_cache_and_recomputes_status(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "gms_mcp.update_notifier.Path.home", return_value=Path(tmpdir)
        ):
            with patch("gms_mcp.update_notifier.get_current_version", return_value="1.0.0"), patch(
                "gms_mcp.update_notifier._utc_now", return_value=1_000.0
            ), patch("gms_mcp.update_notifier.get_latest_version_pypi", return_value="1.3.0"), patch(
                "gms_mcp.update_notifier.get_latest_version_github"
            ):
                first = check_for_updates(force_refresh=True)

            self.assertTrue(first["update_available"])

            with patch("gms_mcp.update_notifier.get_current_version", return_value="1.3.0"), patch(
                "gms_mcp.update_notifier._utc_now", return_value=1_000.0 + 90_000.0
            ), patch("gms_mcp.update_notifier.get_latest_version_pypi", return_value=None), patch(
                "gms_mcp.update_notifier.get_latest_version_github", return_value=None
            ):
                second = check_for_updates()

        self.assertTrue(second["used_cache"])
        self.assertFalse(second["update_available"])
        self.assertEqual(second["status"], "ok")
        self.assertFalse(second["notification_due"])

    def test_no_cache_network_failure_reports_unknown(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "gms_mcp.update_notifier.Path.home", return_value=Path(tmpdir)
        ), patch("gms_mcp.update_notifier.get_current_version", return_value="1.0.0"), patch(
            "gms_mcp.update_notifier.get_latest_version_pypi", return_value=None
        ), patch("gms_mcp.update_notifier.get_latest_version_github", return_value=None):
            result = check_for_updates(force_refresh=True)

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["update_available"])
        self.assertIn("Unable to check", result["message"])

    def test_mark_update_notified_suppresses_repeat_notice(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "gms_mcp.update_notifier.Path.home", return_value=Path(tmpdir)
        ):
            with patch("gms_mcp.update_notifier.get_current_version", return_value="1.0.0"), patch(
                "gms_mcp.update_notifier._utc_now", return_value=1_000.0
            ), patch("gms_mcp.update_notifier.get_latest_version_pypi", return_value="1.1.0"), patch(
                "gms_mcp.update_notifier.get_latest_version_github"
            ):
                first = check_for_updates(force_refresh=True)

            self.assertTrue(first["notification_due"])

            with patch("gms_mcp.update_notifier._utc_now", return_value=1_100.0):
                mark_update_notified(first)

            with patch("gms_mcp.update_notifier.get_current_version", return_value="1.0.0"), patch(
                "gms_mcp.update_notifier._utc_now", return_value=1_200.0
            ):
                second = check_for_updates()

        self.assertTrue(second["used_cache"])
        self.assertFalse(second["notification_due"])


if __name__ == "__main__":
    unittest.main()
