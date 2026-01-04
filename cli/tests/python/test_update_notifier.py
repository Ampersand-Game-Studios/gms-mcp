import json
import unittest
from unittest.mock import patch, MagicMock
from gms_mcp.update_notifier import check_for_updates

class TestUpdateNotifier(unittest.TestCase):
    @patch("gms_mcp.update_notifier.get_current_version")
    @patch("urllib.request.urlopen")
    def test_update_available_pypi(self, mock_urlopen, mock_get_version):
        # Mock current version
        mock_get_version.return_value = "1.0.0"
        
        # Mock PyPI response with a newer version
        mock_pypi_resp = MagicMock()
        mock_pypi_resp.read.return_value = json.dumps({
            "info": {"version": "1.1.0"}
        }).encode()
        mock_pypi_resp.__enter__.return_value = mock_pypi_resp
        
        # Mock GitHub response (same version)
        mock_github_resp = MagicMock()
        mock_github_resp.read.return_value = json.dumps({
            "tag_name": "1.0.0"
        }).encode()
        mock_github_resp.__enter__.return_value = mock_github_resp
        
        mock_urlopen.side_effect = [mock_pypi_resp, mock_github_resp]
        
        result = check_for_updates()
        
        self.assertTrue(result["update_available"])
        self.assertEqual(result["current_version"], "1.0.0")
        self.assertEqual(result["latest_version"], "1.1.0")
        self.assertEqual(result["source"], "PyPI")
        self.assertIn("A newer version", result["message"])

    @patch("gms_mcp.update_notifier.get_current_version")
    @patch("urllib.request.urlopen")
    def test_update_available_github(self, mock_urlopen, mock_get_version):
        # Mock current version
        mock_get_version.return_value = "1.0.0"
        
        # Mock PyPI response (same version)
        mock_pypi_resp = MagicMock()
        mock_pypi_resp.read.return_value = json.dumps({
            "info": {"version": "1.0.0"}
        }).encode()
        mock_pypi_resp.__enter__.return_value = mock_pypi_resp
        
        # Mock GitHub response (newer version with 'v' prefix)
        mock_github_resp = MagicMock()
        mock_github_resp.read.return_value = json.dumps({
            "tag_name": "v1.2.0"
        }).encode()
        mock_github_resp.__enter__.return_value = mock_github_resp
        
        mock_urlopen.side_effect = [mock_pypi_resp, mock_github_resp]
        
        result = check_for_updates()
        
        self.assertTrue(result["update_available"])
        self.assertEqual(result["current_version"], "1.0.0")
        self.assertEqual(result["latest_version"], "1.2.0")
        self.assertEqual(result["source"], "GitHub")

    @patch("gms_mcp.update_notifier.get_current_version")
    @patch("urllib.request.urlopen")
    def test_no_update_needed(self, mock_urlopen, mock_get_version):
        # Mock current version
        mock_get_version.return_value = "1.1.0"
        
        # Mock both responses with same version
        mock_pypi_resp = MagicMock()
        mock_pypi_resp.read.return_value = json.dumps({
            "info": {"version": "1.1.0"}
        }).encode()
        mock_pypi_resp.__enter__.return_value = mock_pypi_resp
        
        mock_github_resp = MagicMock()
        mock_github_resp.read.return_value = json.dumps({
            "tag_name": "1.1.0"
        }).encode()
        mock_github_resp.__enter__.return_value = mock_github_resp
        
        mock_urlopen.side_effect = [mock_pypi_resp, mock_github_resp]
        
        result = check_for_updates()
        
        self.assertFalse(result["update_available"])
        self.assertEqual(result["current_version"], "1.1.0")
        self.assertIn("latest version", result["message"])

    @patch("gms_mcp.update_notifier.get_current_version")
    @patch("urllib.request.urlopen")
    def test_pypi_error_github_fallback(self, mock_urlopen, mock_get_version):
        # Mock current version
        mock_get_version.return_value = "1.0.0"
        
        # PyPI fails, GitHub works
        mock_github_resp = MagicMock()
        mock_github_resp.read.return_value = json.dumps({
            "tag_name": "1.3.0"
        }).encode()
        mock_github_resp.__enter__.return_value = mock_github_resp
        
        mock_urlopen.side_effect = [Exception("PyPI down"), mock_github_resp]
        
        result = check_for_updates()
        
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "1.3.0")
        self.assertEqual(result["source"], "GitHub")

if __name__ == "__main__":
    unittest.main()
