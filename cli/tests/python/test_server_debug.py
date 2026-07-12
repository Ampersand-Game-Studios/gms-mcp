from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gms_mcp.server import debug


class TestServerDebugLog(unittest.TestCase):
    def test_debug_log_redacts_truncates_and_rotates(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.yyp").write_text("{}", encoding="utf-8")
            log_path = project / ".gms_mcp" / "logs" / "debug.log"

            with (
                patch.dict("os.environ", {"GM_PROJECT_ROOT": str(project)}, clear=True),
                patch.object(debug, "_MAX_LOG_BYTES", 500),
                patch.object(debug, "_MAX_STRING_CHARS", 20),
            ):
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


if __name__ == "__main__":
    unittest.main()
