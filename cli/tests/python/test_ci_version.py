from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packaging.version import Version

from scripts import ci_version


class TestCIVersion(unittest.TestCase):
    def test_release_channels_use_documented_branch_names(self):
        with (
            patch.object(ci_version, "_fetch_pypi_versions", return_value=["1.2.3"]),
            patch.dict("os.environ", {"GITHUB_RUN_NUMBER": "42", "GITHUB_RUN_ATTEMPT": "1"}, clear=True),
        ):
            self.assertEqual(
                ci_version._compute_candidate(ref_name="dev").version,
                "1.2.4.dev4200",
            )
            self.assertEqual(
                ci_version._compute_candidate(ref_name="pre-release").version,
                "1.2.4rc4200",
            )
            self.assertEqual(
                ci_version._compute_candidate(ref_name="main").version,
                "1.2.4",
            )

    def test_existing_candidate_is_not_republished(self):
        with (
            patch.object(ci_version, "_fetch_pypi_versions", return_value=["1.2.3", "1.2.4.dev4200"]),
            patch.dict("os.environ", {"GITHUB_RUN_NUMBER": "42"}, clear=True),
        ):
            computed = ci_version._compute_candidate(ref_name="dev")

        self.assertFalse(computed.should_publish)
        self.assertEqual(computed.reason, "version already on PyPI")

    def test_unknown_release_branch_fails_closed(self):
        with patch.object(ci_version, "_fetch_pypi_versions", return_value=["1.2.3"]):
            with self.assertRaises(SystemExit):
                ci_version._compute_candidate(ref_name="feature/unsafe")

    def test_workflow_run_ref_overrides_github_default_branch_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            env = {
                "GITHUB_OUTPUT": str(output),
                "GITHUB_REF_NAME": "main",
                "GITHUB_RUN_NUMBER": "7",
                "RELEASE_REF_NAME": "pre-release",
            }
            with (
                patch.object(ci_version, "_fetch_pypi_versions", return_value=["1.2.3"]),
                patch.dict("os.environ", env, clear=True),
            ):
                self.assertEqual(ci_version.main(), 0)

            self.assertIn("version=1.2.4rc700", output.read_text(encoding="utf-8"))

    def test_latest_final_base_ignores_prereleases(self):
        self.assertEqual(
            ci_version._latest_final_base([Version("2.0.0rc4"), Version("1.9.5"), Version("1.9.5.post2")]),
            Version("1.9.5"),
        )


if __name__ == "__main__":
    unittest.main()
