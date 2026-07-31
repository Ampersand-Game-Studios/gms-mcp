from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gms_mcp.server import debug


class TestServerDebugLog(unittest.TestCase):
    def test_debug_log_redacts_truncates_and_rotates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            home = root / "home"
            project.mkdir()
            home.mkdir()
            (project / "project.yyp").write_text("{}", encoding="utf-8")

            with (
                patch.dict(
                    "os.environ",
                    {"GM_PROJECT_ROOT": str(project), "HOME": str(home), "USERPROFILE": str(home)},
                    clear=True,
                ),
                patch.object(debug, "_MAX_LOG_BYTES", 500),
                patch.object(debug, "_MAX_STRING_CHARS", 20),
            ):
                log_path = debug._get_debug_log_path()
                self.assertIsNotNone(log_path)
                assert log_path is not None
                self.assertTrue(log_path.is_relative_to(home / ".gms-mcp" / "logs"))
                self.assertFalse(log_path.is_relative_to(project))
                debug._dbg(
                    "test",
                    "location",
                    "message",
                    {
                        "api_token": "secret-value",
                        "argv": ["gms-mcp", "--token", "another-secret"],
                        "value": "x" * 60,
                    },
                )
                first = json.loads(log_path.read_text(encoding="utf-8"))
                self.assertEqual(first["data"]["api_token"], "[REDACTED]")
                self.assertNotIn("another-secret", first["data"]["argv"])
                self.assertIn("truncated", first["data"]["value"])

                for index in range(10):
                    debug._dbg("test", "location", "message", {"index": index, "value": "y" * 60})

            self.assertTrue(log_path.exists())
            self.assertTrue(log_path.with_name("debug.log.1").exists())
            self.assertFalse(log_path.with_name("debug.log.4").exists())
            self.assertFalse((project / ".gms_mcp").exists())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(log_path.parent.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
