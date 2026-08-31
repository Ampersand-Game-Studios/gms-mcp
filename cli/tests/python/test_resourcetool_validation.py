from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gms_mcp.resourcetool_validation import (
    RESOURCETOOL_ARGUMENTS_ENV,
    RESOURCETOOL_ENABLED_ENV,
    RESOURCETOOL_EXECUTABLE_ENV,
    RESOURCETOOL_SHA256_ENV,
    _sandboxed_command,
    validate_with_resourcetool,
)


class TestResourceToolValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name) / "private-project"
        self.project.mkdir()
        (self.project / "Game.yyp").write_text('{"resources": []}', encoding="utf-8")
        (self.project / "script.gml").write_text("show_debug_message('hello');", encoding="utf-8")
        self.executable = Path(self.temp_dir.name) / "gm-cli"
        self.executable.write_text("placeholder", encoding="utf-8")
        self.executable.chmod(0o700)
        executable_sha256 = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.environment = {
            RESOURCETOOL_ENABLED_ENV: "1",
            RESOURCETOOL_EXECUTABLE_ENV: str(self.executable),
            RESOURCETOOL_ARGUMENTS_ENV: json.dumps(["resourcetool", "eval", "resource list", "{project_copy_yyp}"]),
            RESOURCETOOL_SHA256_ENV: executable_sha256,
            "PATH": "/private/bin:/usr/bin:/bin",
            "HOME": "/private/home",
            "SECRET_TOKEN": "do-not-pass",
        }
        self.sandbox = patch(
            "gms_mcp.resourcetool_validation._sandboxed_command",
            side_effect=lambda command, **_kwargs: command,
        )
        self.sandbox.start()
        self.addCleanup(self.sandbox.stop)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_disabled_by_default_does_not_copy_or_execute(self) -> None:
        result = validate_with_resourcetool(self.project, environ={})

        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["executed"])
        self.assertFalse(result["evidence"]["copy_created"])

    def test_rejects_non_absolute_or_missing_project(self) -> None:
        with patch("gms_mcp.resourcetool_validation.subprocess.run") as run:
            relative = validate_with_resourcetool("relative", environ=self.environment)
            missing = validate_with_resourcetool(Path(self.temp_dir.name) / "missing", environ=self.environment)

        self.assertEqual(relative["status"], "invalid_project")
        self.assertEqual(missing["status"], "invalid_project")
        run.assert_not_called()

    def test_requires_fixed_official_read_only_contract(self) -> None:
        environment = dict(self.environment, **{RESOURCETOOL_ARGUMENTS_ENV: json.dumps(["--validate"])})

        result = validate_with_resourcetool(self.project, environ=environment)

        self.assertEqual(result["status"], "invalid_arguments")
        self.assertFalse(result["executed"])

    def test_rejects_arbitrary_arguments_even_when_they_name_the_copy(self) -> None:
        environment = dict(
            self.environment,
            **{RESOURCETOOL_ARGUMENTS_ENV: json.dumps(["--project", str(self.project), "{project_copy}"])},
        )
        with patch("gms_mcp.resourcetool_validation.subprocess.run") as run:
            result = validate_with_resourcetool(self.project, environ=environment)

        self.assertEqual(result["status"], "invalid_arguments")
        run.assert_not_called()

    def test_rejects_known_private_project_material_before_copying(self) -> None:
        (self.project / ".env.production").write_text("TOKEN=private", encoding="utf-8")
        with patch("gms_mcp.resourcetool_validation.subprocess.run") as run:
            result = validate_with_resourcetool(self.project, environ=self.environment)

        self.assertEqual(result["status"], "private_project_data")
        self.assertFalse(result["evidence"]["copy_created"])
        run.assert_not_called()

    def test_rejects_additional_private_project_conventions(self) -> None:
        for relative_name in (".netrc", ".npmrc", ".pypirc", ".ssh/known_hosts"):
            with self.subTest(relative_name=relative_name):
                private_path = self.project / relative_name
                private_path.parent.mkdir(parents=True, exist_ok=True)
                private_path.write_text("synthetic-private-data", encoding="utf-8")
                with patch("gms_mcp.resourcetool_validation.subprocess.run") as run:
                    result = validate_with_resourcetool(self.project, environ=self.environment)
                self.assertEqual(result["status"], "private_project_data")
                run.assert_not_called()
                private_path.unlink()
                if private_path.parent != self.project:
                    private_path.parent.rmdir()

    def test_rejects_private_content_in_project_descriptor(self) -> None:
        (self.project / "Game.yyp").write_text(
            '{"API_KEY":"abcdefghijklmnopqrstuvwxyz123456"}',
            encoding="utf-8",
        )

        result = validate_with_resourcetool(self.project, environ=self.environment)

        self.assertEqual(result["status"], "private_project_data")

    def test_requires_an_explicit_executable(self) -> None:
        environment = dict(self.environment)
        environment.pop(RESOURCETOOL_EXECUTABLE_ENV)

        result = validate_with_resourcetool(self.project, environ=environment)

        self.assertEqual(result["status"], "invalid_executable")
        self.assertFalse(result["executed"])

    def test_requires_a_pinned_official_executable_identity(self) -> None:
        environment = dict(self.environment, **{RESOURCETOOL_SHA256_ENV: "0" * 64})

        result = validate_with_resourcetool(self.project, environ=environment)

        self.assertEqual(result["status"], "executable_identity_mismatch")
        self.assertFalse(result["executed"])

    def test_runs_only_against_copy_with_checksums_and_minimal_environment(self) -> None:
        def inspect_minimal_copy(command, **kwargs):
            self.assertEqual(
                {path.name for path in Path(kwargs["cwd"]).iterdir()},
                {"Game.yyp", "script.gml"},
            )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

        with patch("gms_mcp.resourcetool_validation.subprocess.run", side_effect=inspect_minimal_copy) as run:
            result = validate_with_resourcetool(self.project, environ=self.environment)

        command = run.call_args.args[0]
        invocation = run.call_args.kwargs
        self.assertNotIn(str(self.project), command)
        self.assertNotEqual(invocation["cwd"], self.project)
        self.assertFalse(invocation["shell"])
        self.assertNotEqual(invocation["env"]["HOME"], self.environment["HOME"])
        self.assertNotIn("SECRET_TOKEN", invocation["env"])
        self.assertNotEqual(invocation["env"].get("PATH"), self.environment["PATH"])
        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["evidence"]["source_checksum"], result["evidence"]["before_checksum"])
        self.assertEqual(result["evidence"]["before_checksum"], result["evidence"]["after_checksum"])
        self.assertTrue(result["evidence"]["cleanup_completed"])
        self.assertEqual(Path(command[-1]).name, "Game.yyp")
        self.assertFalse(Path(command[-1]).exists())

    def test_fails_closed_when_no_os_sandbox_is_available(self) -> None:
        with patch("gms_mcp.resourcetool_validation.platform.system", return_value="Unsupported"):
            command = _sandboxed_command(
                [str(self.executable)],
                source=self.project,
                temporary_root=Path(self.temp_dir.name),
            )

        self.assertIsNone(command)

    def test_detects_copy_rewrite(self) -> None:
        def rewrite_copy(command, **_kwargs):
            Path(command[-1]).with_name("script.gml").write_text("rewritten", encoding="utf-8")
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        with patch("gms_mcp.resourcetool_validation.subprocess.run", side_effect=rewrite_copy):
            result = validate_with_resourcetool(self.project, environ=self.environment)

        self.assertEqual(result["status"], "rewrote_copy")
        self.assertFalse(result["ok"])
        self.assertTrue(result["evidence"]["rewritten_copy"])
        self.assertEqual((self.project / "script.gml").read_text(encoding="utf-8"), "show_debug_message('hello');")

    def test_detects_attempted_source_rewrite_even_when_the_process_reports_success(self) -> None:
        def rewrite_source(command, **_kwargs):
            (self.project / "script.gml").write_text("rewritten", encoding="utf-8")
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        with patch("gms_mcp.resourcetool_validation.subprocess.run", side_effect=rewrite_source):
            result = validate_with_resourcetool(self.project, environ=self.environment)

        self.assertEqual(result["status"], "source_rewritten")
        self.assertFalse(result["ok"])
        self.assertTrue(result["evidence"]["rewritten_source"])

    def test_detects_validation_failure_and_sanitizes_output(self) -> None:
        private_output = (
            f"Authorization: Bearer synthetic-secret\ntoken=top-secret {self.project}/script.gml\n"
            "GITHUB_TOKEN=abcdefghijklmnopqrstuvwxyz123456\n"
            "ghp_" + ("a" * 24)
        )
        completed = subprocess.CompletedProcess(args=[], returncode=7, stdout=private_output, stderr=private_output)
        with patch("gms_mcp.resourcetool_validation.subprocess.run", return_value=completed):
            result = validate_with_resourcetool(self.project, environ=self.environment)

        rendered = json.dumps(result)
        self.assertEqual(result["status"], "validation_failed")
        self.assertNotIn("top-secret", rendered)
        self.assertNotIn("synthetic-secret", rendered)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", rendered)
        self.assertNotIn(str(self.project), rendered)
        self.assertTrue(result["output_suppressed"])

    def test_detects_timeout_and_cleans_copy(self) -> None:
        def timeout(command, **_kwargs):
            raise subprocess.TimeoutExpired(command, 1, output="/private/output", stderr="password=hidden")

        with patch("gms_mcp.resourcetool_validation.subprocess.run", side_effect=timeout):
            result = validate_with_resourcetool(self.project, timeout_seconds=99_999, environ=self.environment)

        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["evidence"]["timeout_seconds"], 600)
        self.assertTrue(result["evidence"]["cleanup_completed"])
        self.assertNotIn("hidden", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
