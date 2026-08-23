import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gms_mcp.client_registry import CLIENT_SPECS
from gms_mcp.install import main


@contextmanager
def temporary_home(home_dir: Path):
    keys = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
    previous = {key: os.environ.get(key) for key in keys}
    home_str = str(home_dir)
    os.environ["HOME"] = home_str
    os.environ["USERPROFILE"] = home_str
    drive, tail = os.path.splitdrive(home_str)
    if drive:
        os.environ["HOMEDRIVE"] = drive
    if tail:
        os.environ["HOMEPATH"] = tail
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestInstallParity(unittest.TestCase):
    def test_support_matrix_lists_all_clients(self):
        repo_root = Path(__file__).resolve().parents[3]
        matrix_path = repo_root / "documentation" / "CLIENT_SUPPORT_MATRIX.md"
        self.assertTrue(matrix_path.exists())
        content = matrix_path.read_text(encoding="utf-8")
        for spec in CLIENT_SPECS:
            with self.subTest(client=spec.key):
                self.assertIn(f"`{spec.key}`", content)

    def test_sdk_v2_runtime_documentation_covers_public_contract(self):
        repo_root = Path(__file__).resolve().parents[3]
        configuration = (repo_root / "documentation" / "CONFIGURATION.md").read_text(encoding="utf-8")
        support_matrix = (repo_root / "documentation" / "CLIENT_SUPPORT_MATRIX.md").read_text(encoding="utf-8")

        for option in ("--transport", "--host", "--port", "--path"):
            with self.subTest(option=option):
                self.assertIn(f"`{option}`", configuration)
        for protocol in ("2026-07-28", "2025-11-25"):
            with self.subTest(protocol=protocol):
                self.assertIn(protocol, configuration)
                self.assertIn(protocol, support_matrix)
        for capability in ("MCP Apps", "resource subscriptions", "Resolve"):
            with self.subTest(capability=capability):
                self.assertIn(capability, configuration)
                self.assertIn(capability, support_matrix)

    def test_canonical_setup_dry_run_workspace_for_supported_clients(self):
        clients = [spec.key for spec in CLIENT_SPECS if spec.workspace_supported]
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            for client in clients:
                with self.subTest(client=client):
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        code = main(
                            [
                                "--workspace-root",
                                str(workspace),
                                "--non-interactive",
                                "--client",
                                client,
                                "--scope",
                                "workspace",
                                "--action",
                                "setup",
                                "--dry-run",
                            ]
                        )
                    self.assertEqual(code, 0, msg=buf.getvalue())

    def test_canonical_safe_profile_is_default_and_toolsets_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()

            safe_buffer = io.StringIO()
            with redirect_stdout(safe_buffer):
                safe_code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "cursor",
                        "--scope",
                        "workspace",
                        "--action",
                        "setup",
                        "--dry-run",
                    ]
                )
            self.assertEqual(safe_code, 0, msg=safe_buffer.getvalue())
            safe_payload = json.loads(safe_buffer.getvalue()[safe_buffer.getvalue().index("{") :])
            env = safe_payload["mcpServers"]["gms"]["env"]
            self.assertEqual(env["GMS_MCP_TOOLSETS"], "core")
            self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "0")
            self.assertEqual(env["GMS_MCP_REQUIRE_DRY_RUN"], "1")
            self.assertEqual(env["GMS_MCP_READ_ONLY"], "1")
            self.assertNotIn(str(workspace), safe_buffer.getvalue())

            full_buffer = io.StringIO()
            with redirect_stdout(full_buffer):
                full_code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "cursor",
                        "--scope",
                        "workspace",
                        "--action",
                        "setup",
                        "--profile",
                        "full",
                        "--toolsets",
                        "events,rooms",
                        "--dry-run",
                    ]
                )
            self.assertEqual(full_code, 0, msg=full_buffer.getvalue())
            full_payload = json.loads(full_buffer.getvalue()[full_buffer.getvalue().index("{") :])
            self.assertEqual(full_payload["mcpServers"]["gms"]["env"]["GMS_MCP_TOOLSETS"], "events,rooms")
            self.assertEqual(full_payload["mcpServers"]["gms"]["env"]["GMS_MCP_REQUIRE_DRY_RUN"], "0")
            self.assertEqual(full_payload["mcpServers"]["gms"]["env"]["GMS_MCP_READ_ONLY"], "0")

    def test_safe_profile_rejects_mutating_toolset_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "cursor",
                        "--profile",
                        "safe",
                        "--toolsets",
                        "assets",
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("safe profile only supports", buffer.getvalue())

    def test_explicit_full_profile_overrides_antigravity_global_safe_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "antigravity",
                        "--scope",
                        "global",
                        "--profile",
                        "full",
                        "--config-path",
                        str(workspace / "mcp.json"),
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 0, msg=buffer.getvalue())
            payload = json.loads(buffer.getvalue()[buffer.getvalue().index("{") :].split("\n{", 1)[0])
            env = payload["mcpServers"]["gms"]["env"]
            self.assertEqual(env["GMS_MCP_TOOLSETS"], "all")
            self.assertEqual(env["GMS_MCP_READ_ONLY"], "0")
            self.assertEqual(env["GMS_MCP_REQUIRE_DRY_RUN"], "0")
            self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "1")

    def test_explicit_standard_and_full_clear_inherited_safe_profile_controls(self):
        inherited = {
            "GMS_MCP_ENABLE_DIRECT": "0",
            "GMS_MCP_REQUIRE_DRY_RUN": "1",
            "GMS_MCP_READ_ONLY": "1",
            "GMS_MCP_TOOLSETS": "core",
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, inherited, clear=False):
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            for profile, expected_toolsets in (("standard", "core"), ("full", "all")):
                with self.subTest(profile=profile):
                    buffer = io.StringIO()
                    with redirect_stdout(buffer):
                        code = main(
                            [
                                "--workspace-root",
                                str(workspace),
                                "--non-interactive",
                                "--client",
                                "cursor",
                                "--scope",
                                "workspace",
                                "--profile",
                                profile,
                                "--action",
                                "setup",
                                "--dry-run",
                            ]
                        )
                    self.assertEqual(code, 0, msg=buffer.getvalue())
                    payload = json.loads(buffer.getvalue()[buffer.getvalue().index("{") :])
                    env = payload["mcpServers"]["gms"]["env"]
                    self.assertEqual(env["GMS_MCP_TOOLSETS"], expected_toolsets)
                    self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "1")
                    self.assertEqual(env["GMS_MCP_REQUIRE_DRY_RUN"], "0")
                    self.assertEqual(env["GMS_MCP_READ_ONLY"], "0")

    def test_canonical_toolsets_are_validated_before_writing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "cursor",
                        "--toolsets",
                        "not-a-toolset",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("Unsupported toolset", buffer.getvalue())

    def test_canonical_check_json_redacts_private_paths_and_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            config_path = workspace / "mcp.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "gms": {
                                "command": str(workspace / "private" / "gms-mcp"),
                                "args": [f"--project={workspace / 'private'}"],
                                "env": {
                                    "GM_PROJECT_ROOT": str(workspace / "private"),
                                    "PYTHONUNBUFFERED": "1",
                                    "API_KEY": "not-for-output",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "cursor",
                        "--action",
                        "check-json",
                        "--config-path",
                        str(config_path),
                    ]
                )
            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertNotIn(str(workspace), output)
            self.assertNotIn("not-for-output", output)
            payload = json.loads(output)
            self.assertEqual(payload["config"]["path"], "<host-path>")
            self.assertEqual(payload["config"]["entry"]["env"]["API_KEY"], "***REDACTED***")

    def test_canonical_setup_global_for_supported_clients(self):
        clients = [spec.key for spec in CLIENT_SPECS if spec.global_supported]
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            (workspace / "project.yyp").touch()
            home_dir = Path(tmpdir) / "home"
            with temporary_home(home_dir):
                for client in clients:
                    with self.subTest(client=client):
                        setup_buffer = io.StringIO()
                        with redirect_stdout(setup_buffer):
                            setup_code = main(
                                [
                                    "--workspace-root",
                                    str(workspace),
                                    "--non-interactive",
                                    "--client",
                                    client,
                                    "--scope",
                                    "global",
                                    "--action",
                                    "setup",
                                ]
                            )
                        self.assertEqual(setup_code, 0, msg=setup_buffer.getvalue())

                        check_buffer = io.StringIO()
                        with redirect_stdout(check_buffer):
                            check_code = main(
                                [
                                    "--workspace-root",
                                    str(workspace),
                                    "--non-interactive",
                                    "--client",
                                    client,
                                    "--scope",
                                    "global",
                                    "--action",
                                    "check-json",
                                ]
                            )
                        self.assertEqual(check_code, 0, msg=check_buffer.getvalue())
                        payload = json.loads(check_buffer.getvalue())
                        self.assertEqual(payload["client"], client)
                        self.assertEqual(payload["scope"], "global")
                        self.assertFalse(payload["not_applicable"])
                        self.assertIn("active", payload)
                        self.assertIn("entry", payload["active"])

    def test_legacy_and_canonical_cursor_outputs_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_workspace = Path(tmpdir) / "legacy"
            canonical_workspace = Path(tmpdir) / "canonical"
            legacy_workspace.mkdir()
            canonical_workspace.mkdir()
            (legacy_workspace / "project.yyp").touch()
            (canonical_workspace / "project.yyp").touch()

            legacy_buffer = io.StringIO()
            with redirect_stdout(legacy_buffer):
                legacy_code = main(
                    [
                        "--workspace-root",
                        str(legacy_workspace),
                        "--non-interactive",
                        "--cursor",
                    ]
                )
            self.assertEqual(legacy_code, 0, msg=legacy_buffer.getvalue())

            canonical_buffer = io.StringIO()
            with redirect_stdout(canonical_buffer):
                canonical_code = main(
                    [
                        "--workspace-root",
                        str(canonical_workspace),
                        "--non-interactive",
                        "--client",
                        "cursor",
                        "--scope",
                        "workspace",
                        "--action",
                        "setup",
                        "--profile",
                        "standard",
                    ]
                )
            self.assertEqual(canonical_code, 0, msg=canonical_buffer.getvalue())

            legacy_config = json.loads((legacy_workspace / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            canonical_config = json.loads((canonical_workspace / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            canonical_env = canonical_config["mcpServers"]["gms"]["env"]
            self.assertEqual(canonical_env.pop("GMS_MCP_ENABLE_DIRECT"), "1")
            self.assertEqual(canonical_env.pop("GMS_MCP_REQUIRE_DRY_RUN"), "0")
            self.assertEqual(canonical_env.pop("GMS_MCP_READ_ONLY"), "0")
            self.assertEqual(canonical_env.pop("GMS_MCP_TOOLSETS"), "core")
            self.assertEqual(legacy_config, canonical_config)

    def test_canonical_check_json_schema_workspace(self):
        clients = [spec.key for spec in CLIENT_SPECS if spec.workspace_supported]
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            for client in clients:
                with self.subTest(client=client):
                    setup_buffer = io.StringIO()
                    with redirect_stdout(setup_buffer):
                        setup_code = main(
                            [
                                "--workspace-root",
                                str(workspace),
                                "--non-interactive",
                                "--client",
                                client,
                                "--scope",
                                "workspace",
                                "--action",
                                "setup",
                            ]
                        )
                    self.assertEqual(setup_code, 0, msg=setup_buffer.getvalue())

                    check_buffer = io.StringIO()
                    with redirect_stdout(check_buffer):
                        check_code = main(
                            [
                                "--workspace-root",
                                str(workspace),
                                "--non-interactive",
                                "--client",
                                client,
                                "--scope",
                                "workspace",
                                "--action",
                                "check-json",
                            ]
                        )
                    self.assertEqual(check_code, 0, msg=check_buffer.getvalue())
                    payload = json.loads(check_buffer.getvalue())
                    self.assertTrue(payload["ok"])
                    self.assertIn("client", payload)
                    self.assertIn("scope", payload)
                    self.assertIn("config", payload)
                    self.assertIn("active", payload)
                    self.assertIn("ready", payload)
                    self.assertIn("problems", payload)
                    self.assertIn("not_applicable", payload)
                    self.assertEqual(payload["scope"], "workspace")
                    self.assertFalse(payload["not_applicable"])

    def test_not_applicable_scope_for_claude_code_global(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "claude-code",
                        "--scope",
                        "global",
                        "--action",
                        "check-json",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["client"], "claude-code")
            self.assertTrue(payload["not_applicable"])
            self.assertFalse(payload["ready"])

    def test_not_applicable_scope_for_claude_desktop_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "claude-desktop",
                        "--scope",
                        "workspace",
                        "--action",
                        "check-json",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["client"], "claude-desktop")
            self.assertTrue(payload["not_applicable"])
            self.assertFalse(payload["ready"])

    def test_gemini_alias_uses_antigravity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            setup_buffer = io.StringIO()
            with redirect_stdout(setup_buffer):
                setup_code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "gemini",
                        "--scope",
                        "workspace",
                        "--action",
                        "setup",
                    ]
                )
            self.assertEqual(setup_code, 0, msg=setup_buffer.getvalue())

            check_buffer = io.StringIO()
            with redirect_stdout(check_buffer):
                check_code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "gemini",
                        "--scope",
                        "workspace",
                        "--action",
                        "check-json",
                    ]
                )
            self.assertEqual(check_code, 0, msg=check_buffer.getvalue())
            payload = json.loads(check_buffer.getvalue())
            self.assertEqual(payload["client"], "antigravity")
            self.assertEqual(payload["scope"], "workspace")

    def test_claude_desktop_global_setup_syncs_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            (workspace / "project.yyp").touch()
            home_dir = Path(tmpdir) / "home"
            with temporary_home(home_dir):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = main(
                        [
                            "--workspace-root",
                            str(workspace),
                            "--non-interactive",
                            "--client",
                            "claude-desktop",
                            "--scope",
                            "global",
                            "--action",
                            "setup",
                        ]
                    )
                self.assertEqual(code, 0, msg=buffer.getvalue())
                plugin_dir = home_dir / ".claude" / "plugins" / "gms-mcp"
                self.assertTrue((plugin_dir / ".claude-plugin" / "plugin.json").exists())
                self.assertTrue((plugin_dir / ".mcp.json").exists())
                self.assertTrue((plugin_dir / "hooks").exists())
                self.assertTrue((plugin_dir / "skills").exists())

    def test_openclaw_app_setup_can_install_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "openclaw",
                        "--scope",
                        "workspace",
                        "--action",
                        "app-setup",
                        "--openclaw-install-skills",
                        "--openclaw-skills-project",
                    ]
                )
            self.assertEqual(code, 0, msg=buffer.getvalue())
            self.assertTrue((workspace / "skills" / "gms-mcp" / "SKILL.md").exists())

    def test_malformed_cursor_config_reports_actionable_problem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            cursor_path = workspace / ".cursor" / "mcp.json"
            cursor_path.parent.mkdir(parents=True, exist_ok=True)
            cursor_path.write_text("{ bad json", encoding="utf-8")

            check_buffer = io.StringIO()
            with redirect_stdout(check_buffer):
                check_code = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--client",
                        "cursor",
                        "--scope",
                        "workspace",
                        "--action",
                        "check-json",
                    ]
                )
            self.assertEqual(check_code, 0, msg=check_buffer.getvalue())
            payload = json.loads(check_buffer.getvalue())
            self.assertFalse(payload["ready"])
            self.assertFalse(payload["not_applicable"])
            self.assertGreater(len(payload["problems"]), 0)
            self.assertIn("Malformed JSON", payload["problems"][0])


if __name__ == "__main__":
    unittest.main()
