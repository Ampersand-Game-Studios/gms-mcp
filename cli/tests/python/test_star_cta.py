import io
import json
import tempfile
import unittest
from pathlib import Path

from gms_mcp.star_cta import HELP_EPILOG, STAR_CTA_DISABLE_ENV, maybe_print_star_cta


class _TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class TestStarCTA(unittest.TestCase):
    def test_help_epilog_mentions_repo_and_star_prompt(self):
        self.assertIn("Project:", HELP_EPILOG)
        self.assertIn("star the repo on GitHub", HELP_EPILOG)

    def test_maybe_print_star_cta_requires_tty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "ux.json"
            shown = maybe_print_star_cta(stream=io.StringIO(), env={}, state_path=state_path)

        self.assertFalse(shown)
        self.assertFalse(state_path.exists())

    def test_maybe_print_star_cta_prints_once_and_records_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "ux.json"
            first = _TTYBuffer()
            second = _TTYBuffer()

            first_shown = maybe_print_star_cta(stream=first, env={}, state_path=state_path)
            second_shown = maybe_print_star_cta(stream=second, env={}, state_path=state_path)

            self.assertTrue(first_shown)
            self.assertFalse(second_shown)
            self.assertIn("GitHub star helps other GameMaker users find gms-mcp", first.getvalue())
            self.assertIn(STAR_CTA_DISABLE_ENV, first.getvalue())
            self.assertEqual(second.getvalue(), "")

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(state["star_cta"]["shown"])
            self.assertIn("last_shown_at", state["star_cta"])

    def test_maybe_print_star_cta_respects_disable_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "ux.json"
            buffer = _TTYBuffer()

            shown = maybe_print_star_cta(
                stream=buffer,
                env={STAR_CTA_DISABLE_ENV: "1"},
                state_path=state_path,
            )

        self.assertFalse(shown)
        self.assertEqual(buffer.getvalue(), "")
        self.assertFalse(state_path.exists())

    def test_maybe_print_star_cta_skips_ci(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "ux.json"
            buffer = _TTYBuffer()

            shown = maybe_print_star_cta(stream=buffer, env={"CI": "true"}, state_path=state_path)

        self.assertFalse(shown)
        self.assertEqual(buffer.getvalue(), "")
        self.assertFalse(state_path.exists())
