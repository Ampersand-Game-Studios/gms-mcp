import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

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
                    ]
                )
            self.assertEqual(canonical_code, 0, msg=canonical_buffer.getvalue())

            legacy_config = (legacy_workspace / ".cursor" / "mcp.json").read_text(encoding="utf-8")
            canonical_config = (canonical_workspace / ".cursor" / "mcp.json").read_text(encoding="utf-8")
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
