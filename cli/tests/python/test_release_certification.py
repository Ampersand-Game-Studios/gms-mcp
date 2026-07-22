from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_release_certification import REQUIRED_CERTIFICATIONS, _runtime_version_matches, verify_reports


REPO_ROOT = Path(__file__).resolve().parents[3]


def _report(name: str, *, host_platform: str = "macos", status: str = "passed") -> dict:
    passed = status == "passed"
    version = "2026.1.0.100" if name == "gm-2026-lts" else "2024.14.4.268"
    source_suffix = "2026" if name == "gm-2026-lts" else "2024"
    return {
        "ok": passed,
        "status": status,
        "fixture": {
            "name": name,
            "host_platform": host_platform,
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
            for certification_id in REQUIRED_CERTIFICATIONS:
                host_platform, name = certification_id.split("-", 1)
                (root / f"real_gamemaker_smoke-{certification_id}.json").write_text(
                    json.dumps(_report(name, host_platform=host_platform)),
                    encoding="utf-8",
                )

            self.assertEqual(verify_reports(root, list(REQUIRED_CERTIFICATIONS)), [])

    def test_source_yyp_name_must_not_expose_a_host_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            payload["fixture"]["source_yyp_name"] = "C:\\fixtures\\gm-2024\\Fixture2024.yyp"
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2024"])

        self.assertTrue(any("privacy-safe filename" in error for error in errors))

    def test_skipped_or_missing_fixture_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(
                json.dumps(_report("gm-2024", status="skipped")), encoding="utf-8"
            )

            errors = verify_reports(root, ["macos-gm-2024", "macos-gm-2026-lts"])

        self.assertTrue(any("did not pass" in error for error in errors))
        self.assertTrue(any("Missing" in error for error in errors))

    def test_missing_semantic_check_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            payload["checks"]["deferred_batch_flushed"] = False
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2024"])

        self.assertEqual(len(errors), 1)
        self.assertIn("deferred_batch_flushed", errors[0])

    def test_runtime_must_match_exact_fixture_expectation_not_only_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            payload["fixture"]["expected_runtime_version"] = "2024.14.4.999"
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2024"])

        self.assertTrue(any("does not match configured expectation" in error for error in errors))

    def test_different_fixtures_with_same_source_yyp_hash_block_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = {name: _report(name) for name in ("gm-2024", "gm-2026-lts")}
            reports["gm-2026-lts"]["fixture"]["source_yyp_sha256"] = reports["gm-2024"]["fixture"]["source_yyp_sha256"]
            for name, payload in reports.items():
                (root / f"real_gamemaker_smoke-{name}.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2024", "macos-gm-2026-lts"])

        self.assertTrue(any("Different real GameMaker fixtures must have distinct" in error for error in errors))

    def test_same_fixture_must_be_identical_on_every_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            macos = _report("gm-2024", host_platform="macos")
            windows = _report("gm-2024", host_platform="windows")
            windows["fixture"]["source_yyp_sha256"] = "a" * 64
            (root / "real_gamemaker_smoke-macos-gm-2024.json").write_text(json.dumps(macos), encoding="utf-8")
            (root / "real_gamemaker_smoke-windows-gm-2024.json").write_text(json.dumps(windows), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2024", "windows-gm-2024"])

        self.assertTrue(any("same source YYP SHA-256 on every platform" in error for error in errors))

    def test_missing_host_platform_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            del payload["fixture"]["host_platform"]
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2024"])

        self.assertTrue(any("invalid host platform" in error for error in errors))

    def test_wrong_source_ide_version_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2026-lts")
            payload["fixture"]["source_ide_version"] = "2024.14.3.217"
            (root / "real_gamemaker_smoke-gm-2026-lts.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2026-lts"])

        self.assertTrue(any("source IDEVersion" in error and "expected 2026.*" in error for error in errors))

    def test_missing_source_provenance_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _report("gm-2024")
            del payload["fixture"]["source_yyp_sha256"]
            (root / "real_gamemaker_smoke-gm-2024.json").write_text(json.dumps(payload), encoding="utf-8")

            errors = verify_reports(root, ["macos-gm-2024"])

        self.assertTrue(any("missing source provenance" in error and "source_yyp_sha256" in error for error in errors))

    def test_publish_workflow_is_ci_and_real_smoke_gated(self):
        publish = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_run:", publish)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", publish)
        self.assertIn("github.event.workflow_run.event == 'push'", publish)
        self.assertIn("vars.GMS_MCP_REAL_SMOKE_ENABLED == 'true'", publish)
        self.assertIn("verify_release_certification.py", publish)
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", publish)
        self.assertNotIn("workflow_dispatch", publish)
        self.assertNotIn("github.sha", publish)

    def test_ci_covers_every_promotion_branch(self):
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        for branch in ("dev", "pre-release", "main"):
            self.assertGreaterEqual(ci.count(f'- "{branch}"'), 2)
        self.assertIn("if: github.event_name == 'push' && vars.GMS_MCP_REAL_SMOKE_ENABLED == 'true'", ci)
        self.assertIn("runner: macos-15", ci)
        self.assertIn("runner: windows-2025", ci)
        self.assertIn("runner: ubuntu-24.04", ci)
        self.assertIn("runs-on: ${{ matrix.runner }}", ci)
        self.assertIn("GAMEMAKER_ACCESS_KEY: ${{ secrets.GAMEMAKER_ACCESS_KEY }}", ci)
        self.assertIn("scripts/setup_gamemaker_ci.py", ci)
        self.assertNotIn("self-hosted", ci)
        self.assertNotIn("GMS_MCP_REAL_SMOKE_RUNNER_LABELS", ci)
        self.assertIn("REAL_GAMEMAKER_SMOKE_ENABLED: ${{ vars.GMS_MCP_REAL_SMOKE_ENABLED }}", ci)
        self.assertIn("REAL_GAMEMAKER_SMOKE_RESULT: ${{ needs.real_gamemaker_smoke.result }}", ci)
        self.assertIn('if [ "$EVENT_NAME" = "push" ] && [ "$REAL_GAMEMAKER_SMOKE_ENABLED" = "true" ]; then', ci)
        self.assertIn('elif [ "$REAL_GAMEMAKER_SMOKE_RESULT" != "skipped" ]; then', ci)
        self.assertIn("ruff format --check .", ci)
        self.assertNotIn("vars[matrix.project_var]", ci)
        self.assertNotIn("GMS_MCP_REAL_SMOKE_PROJECT", ci)
        self.assertNotIn("project_env", ci)
        self.assertIn("--expected-runtime-version", ci)
        self.assertIn("--privacy-safe-output", ci)
        self.assertIn("--cleanup", ci)
        self.assertIn("astral-sh/setup-uv@", ci)
        self.assertIn("uv sync --frozen", ci)
        self.assertNotIn("pip install", ci)

    def test_gamemaker_ci_setup_is_pinned_and_suppresses_private_vendor_output(self):
        setup = (REPO_ROOT / "scripts" / "setup_gamemaker_ci.py").read_text(encoding="utf-8")

        self.assertIn("https://gms.yoyogames.com/igor_osx-arm64.zip", setup)
        self.assertIn("https://gms.yoyogames.com/igor_win-x64.zip", setup)
        self.assertIn("https://gms.yoyogames.com/igor_linux-x64.zip", setup)
        self.assertIn("850260ede5f591000533d760a2c0379bd753e5a6ebb0db30e1003c7957ca1599", setup)
        self.assertIn("2036f66ac7c3a5d195434a4be528d6d9b62bffd89a65bd664c174168749bc561", setup)
        self.assertIn("ffebba4bfc90de0a6fe23f9767179bdd4336d10358555a7e3e649d6aeb91ddc0", setup)
        self.assertIn("2024.14.4.268", setup)
        self.assertIn("2026.0.0.23", setup)
        self.assertIn("stdout=subprocess.DEVNULL", setup)
        self.assertIn("stderr=subprocess.DEVNULL", setup)
        self.assertIn('os.environ.pop("GAMEMAKER_ACCESS_KEY", None)', setup)
        self.assertIn("license_file.chmod(0o600)", setup)
        self.assertNotIn("set -x", setup)


if __name__ == "__main__":
    unittest.main()
