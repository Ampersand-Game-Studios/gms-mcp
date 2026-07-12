from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_release_certification import _runtime_version_matches, verify_reports


REPO_ROOT = Path(__file__).resolve().parents[3]


def _report(name: str, *, status: str = "passed") -> dict:
    passed = status == "passed"
    version = "2026.1.0.100" if name == "gm-2026-lts" else "2024.14.4.268"
    source_suffix = "2026" if name == "gm-2026-lts" else "2024"
    return {
        "ok": passed,
        "status": status,
        "fixture": {
            "name": name,
            "expected_runtime_version": version,
            "source_yyp_name": f"Fixture{source_suffix}.yyp",
            "source_yyp_sha256": source_suffix * 16,
            "source_ide_version": f"{source_suffix}.0.0.1",
        },
        "runtime": {
            "ok": passed,
            "version": version if passed else "",
            "channel": "lts" if name == "gm-2026-lts" else "stable",
        },
        "checks": {
            "high_risk_mutation_compiled": passed,
            "batchable_mutation_deferred": passed,
            "deferred_batch_flushed": passed,
            "collision_reference_emitted": passed,
            "collision_event_compiled": passed,
            "collision_target_rename_schema": passed,
            "collision_target_rename_compiled": passed,
            "room_order_duplicate_delete_schema": passed,
            "room_order_changes_compiled": passed,
        },
    }


class TestReleaseCertification(unittest.TestCase):
    def test_runtime_expectations_are_exact_unless_they_contain_a_glob(self):
        self.assertTrue(_runtime_version_matches("2024.14.4.268", "2024.14.4.268"))
        self.assertFalse(_runtime_version_matches("2024.14.4.268999", "2024.14.4.268"))
        self.assertTrue(_runtime_version_matches("2024.14.4.268", "2024.*"))

    def test_all_required_real_fixtures_must_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("gm-2024", "gm-2026-lts"):
                (root / f"real_gamemaker_smoke-{name}.json").write_text(json.dumps(_report(name)), encoding="utf-8")

            self.assertEqual(verify_reports(root, ["gm-2024", "gm-2026-lts"]), [])

    def test_source_yyp_name_must_not_expose_a_host_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            payload["fixture"]["source_yyp_name"] = "C:\\fixtures\\gm-2024\\Fixture2024.yyp"
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["gm-2024"])

        self.assertTrue(any("privacy-safe filename" in error for error in errors))

    def test_skipped_or_missing_fixture_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(
                json.dumps(_report("gm-2024", status="skipped")), encoding="utf-8"
            )

            errors = verify_reports(root, ["gm-2024", "gm-2026-lts"])

        self.assertTrue(any("did not pass" in error for error in errors))
        self.assertTrue(any("Missing" in error for error in errors))

    def test_missing_semantic_check_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            payload["checks"]["deferred_batch_flushed"] = False
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["gm-2024"])

        self.assertEqual(len(errors), 1)
        self.assertIn("deferred_batch_flushed", errors[0])

    def test_runtime_must_match_exact_fixture_expectation_not_only_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            payload["fixture"]["expected_runtime_version"] = "2024.14.4.999"
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["gm-2024"])

        self.assertTrue(any("does not match configured expectation" in error for error in errors))

    def test_same_source_yyp_hash_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = {name: _report(name) for name in ("gm-2024", "gm-2026-lts")}
            reports["gm-2026-lts"]["fixture"]["source_yyp_sha256"] = reports["gm-2024"]["fixture"]["source_yyp_sha256"]
            for name, payload in reports.items():
                (root / f"real_gamemaker_smoke-{name}.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["gm-2024", "gm-2026-lts"])

        self.assertTrue(any("source YYP SHA-256 hashes must be distinct" in error for error in errors))

    def test_wrong_source_ide_version_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2026-lts")
            payload["fixture"]["source_ide_version"] = "2024.14.3.217"
            (root / "real_gamemaker_smoke-gm-2026-lts.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["gm-2026-lts"])

        self.assertTrue(any("source IDEVersion" in error and "expected 2026.*" in error for error in errors))

    def test_missing_source_provenance_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            del payload["fixture"]["source_yyp_sha256"]
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["gm-2024"])

        self.assertTrue(any("missing source provenance" in error and "source_yyp_sha256" in error for error in errors))

    def test_publish_workflow_is_ci_and_real_smoke_gated(self):
        publish = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_run:", publish)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", publish)
        self.assertIn("github.event.workflow_run.event == 'push'", publish)
        self.assertIn("verify_release_certification.py", publish)
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", publish)
        self.assertNotIn("workflow_dispatch", publish)
        self.assertNotIn("github.sha", publish)

    def test_ci_covers_every_promotion_branch(self):
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        for branch in ("dev", "pre-release", "main"):
            self.assertGreaterEqual(ci.count(f'- "{branch}"'), 2)
        self.assertIn("GMS_MCP_REAL_SMOKE_RUNNER_LABELS", ci)
        self.assertIn("GMS_MCP_REQUIRE_REAL_GAMEMAKER_SMOKE=1", ci)
        self.assertIn("ruff format --check .", ci)
        self.assertNotIn("vars[matrix.project_var]", ci)
        self.assertNotIn("GMS_MCP_REAL_SMOKE_PROJECT: ${{ vars", ci)
        self.assertIn("astral-sh/setup-uv@", ci)
        self.assertIn("uv sync --frozen", ci)
        self.assertNotIn("pip install", ci)


if __name__ == "__main__":
    unittest.main()
