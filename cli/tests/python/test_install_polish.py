import unittest
import os
import json
import tempfile
import io
from contextlib import redirect_stdout, contextmanager
from pathlib import Path
from gms_mcp.install import (
    _make_server_config,
    _workspace_folder_var,
    _make_claude_code_plugin_manifest,
    _make_claude_code_mcp_config,
    _make_codex_toml_value,
    _build_codex_env,
    _build_codex_env_args,
    _make_codex_mcp_config,
    _parse_toml_or_raise,
    _validate_codex_sections,
    _toml_parser,
    _upsert_codex_server_config,
    _generate_codex_config,
    _generate_claude_code_plugin,
    main,
)


@contextmanager
def temporary_home(home_dir: Path):
    """Temporarily point home-directory env vars at a test location."""
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
        for key, val in previous.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


class TestInstallAutodetect(unittest.TestCase):
    def test_make_server_config_autodetect(self):
        # Set some environment variables to detect
        os.environ["GMS_MCP_GMS_PATH"] = "C:\\path\\to\\gms.exe"
        os.environ["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = "60"
        os.environ["GMS_MCP_ENABLE_DIRECT"] = "1"
        
        try:
            config = _make_server_config(
                client="cursor",
                server_name="gms-test",
                command="gms-mcp",
                args=[],
                gm_project_root_rel_posix="gamemaker"
            )
            
            env = config["mcpServers"]["gms-test"]["env"]
            
            self.assertEqual(env["GMS_MCP_GMS_PATH"], "C:\\path\\to\\gms.exe")
            self.assertEqual(env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"], "60")
            self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "1")
            self.assertEqual(env["GM_PROJECT_ROOT"], "${workspaceFolder}/gamemaker")
            
        finally:
            # Clean up env vars
            for var in ["GMS_MCP_GMS_PATH", "GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "GMS_MCP_ENABLE_DIRECT"]:
                if var in os.environ:
                    del os.environ[var]

    def test_make_server_config_no_autodetect(self):
        # Ensure they AREN'T set
        for var in ["GMS_MCP_GMS_PATH", "GMS_MCP_DEFAULT_TIMEOUT_SECONDS", "GMS_MCP_ENABLE_DIRECT"]:
            if var in os.environ:
                del os.environ[var]
                
        config = _make_server_config(
            client="cursor",
            server_name="gms-test",
            command="gms-mcp",
            args=[],
            gm_project_root_rel_posix=None
        )
        
        env = config["mcpServers"]["gms-test"]["env"]
        
        self.assertNotIn("GMS_MCP_GMS_PATH", env)
        self.assertNotIn("GMS_MCP_DEFAULT_TIMEOUT_SECONDS", env)
        self.assertNotIn("GMS_MCP_ENABLE_DIRECT", env)
        self.assertEqual(env["GM_PROJECT_ROOT"], "${workspaceFolder}")

class TestClaudeCodeSupport(unittest.TestCase):
    """Tests for Claude Code plugin generation."""

    def _require_toml_parser(self):
        if _toml_parser is None:
            self.skipTest("TOML parser unavailable in this runtime.")

    def test_workspace_folder_var_cursor(self):
        """Cursor should use ${workspaceFolder}."""
        self.assertEqual(_workspace_folder_var("cursor"), "${workspaceFolder}")

    def test_workspace_folder_var_vscode(self):
        """VS Code should use ${workspaceFolder}."""
        self.assertEqual(_workspace_folder_var("vscode"), "${workspaceFolder}")

    def test_workspace_folder_var_claude_code(self):
        """Claude Code should use ${CLAUDE_PROJECT_DIR}."""
        self.assertEqual(_workspace_folder_var("claude-code"), "${CLAUDE_PROJECT_DIR}")

    def test_workspace_folder_var_claude_code_global(self):
        """Claude Code global should use ${CLAUDE_PROJECT_DIR}."""
        self.assertEqual(_workspace_folder_var("claude-code-global"), "${CLAUDE_PROJECT_DIR}")

    def test_make_claude_code_plugin_manifest_structure(self):
        """Plugin manifest should have required fields."""
        manifest = _make_claude_code_plugin_manifest()

        self.assertIn("name", manifest)
        self.assertEqual(manifest["name"], "gms-mcp")
        self.assertIn("description", manifest)
        self.assertIn("version", manifest)
        self.assertIn("author", manifest)
        self.assertIn("name", manifest["author"])
        self.assertIn("repository", manifest)
        self.assertIn("license", manifest)
        self.assertIn("keywords", manifest)
        self.assertIsInstance(manifest["keywords"], list)

    def test_make_claude_code_mcp_config_structure(self):
        """MCP config should have correct structure with CLAUDE_PROJECT_DIR."""
        config = _make_claude_code_mcp_config(
            server_name="gms",
            command="gms-mcp",
            args=[],
        )

        self.assertIn("gms", config)
        server = config["gms"]
        self.assertEqual(server["command"], "gms-mcp")
        self.assertEqual(server["args"], [])
        self.assertIn("env", server)
        self.assertEqual(server["env"]["GM_PROJECT_ROOT"], "${CLAUDE_PROJECT_DIR}")
        self.assertEqual(server["env"]["PYTHONUNBUFFERED"], "1")

    def test_make_claude_code_mcp_config_custom_server_name(self):
        """MCP config should use custom server name."""
        config = _make_claude_code_mcp_config(
            server_name="custom-gms",
            command="python",
            args=["-m", "gms_mcp.bootstrap_server"],
        )

        self.assertIn("custom-gms", config)
        self.assertNotIn("gms", config)
        server = config["custom-gms"]
        self.assertEqual(server["command"], "python")
        self.assertEqual(server["args"], ["-m", "gms_mcp.bootstrap_server"])

    def test_make_claude_code_mcp_config_env_autodetect(self):
        """MCP config should include detected environment variables."""
        os.environ["GMS_MCP_GMS_PATH"] = "/path/to/gms"
        os.environ["GMS_MCP_ENABLE_DIRECT"] = "1"

        try:
            config = _make_claude_code_mcp_config(
                server_name="gms",
                command="gms-mcp",
                args=[],
            )

            env = config["gms"]["env"]
            self.assertEqual(env["GMS_MCP_GMS_PATH"], "/path/to/gms")
            self.assertEqual(env["GMS_MCP_ENABLE_DIRECT"], "1")
        finally:
            del os.environ["GMS_MCP_GMS_PATH"]
            del os.environ["GMS_MCP_ENABLE_DIRECT"]

    def test_make_codex_mcp_config_structure(self):
        """Codex config should produce a valid TOML block."""
        workspace_root = Path("/tmp/workspace")
        config = _make_codex_mcp_config(
            server_name="gms-codex",
            command="gms-mcp",
            args=[],
            gm_project_root=None,
            workspace_root=workspace_root,
        )

        self.assertIn("[mcp_servers.gms-codex]", config)
        self.assertIn('command = "gms-mcp"', config)
        self.assertIn(
            f"GM_PROJECT_ROOT = {_make_codex_toml_value(str(workspace_root))}",
            config,
        )
        self.assertIn("[mcp_servers.gms-codex.env]", config)

    def test_make_codex_mcp_config_env_autodetect(self):
        """Codex config should include detected environment variables."""
        os.environ["GMS_MCP_GMS_PATH"] = "/path/to/gms"
        os.environ["GMS_MCP_ENABLE_DIRECT"] = "1"
        gm_root = Path("/tmp/workspace/gamemaker")
        workspace_root = Path("/tmp/workspace")

        try:
            config = _make_codex_mcp_config(
                server_name="gms",
                command="gms-mcp",
                args=[],
                gm_project_root=gm_root,
                workspace_root=workspace_root,
            )
            self.assertIn('GMS_MCP_GMS_PATH = "/path/to/gms"', config)
            self.assertIn('GMS_MCP_ENABLE_DIRECT = "1"', config)
            self.assertIn(
                f"GM_PROJECT_ROOT = {_make_codex_toml_value(str(gm_root))}",
                config,
            )
        finally:
            del os.environ["GMS_MCP_GMS_PATH"]
            del os.environ["GMS_MCP_ENABLE_DIRECT"]

    def test_build_codex_toml_value(self):
        """Serializer should produce TOML-compatible scalar output."""
        self.assertEqual(_make_codex_toml_value(True), "true")
        self.assertEqual(_make_codex_toml_value(False), "false")
        self.assertEqual(_make_codex_toml_value(7), "7")
        self.assertEqual(_make_codex_toml_value(3.5), "3.5")
        self.assertEqual(_make_codex_toml_value("value"), '"value"')
        self.assertEqual(_make_codex_toml_value(["a", "b"]), '["a", "b"]')

    def test_build_codex_env_and_args(self):
        """Codex env helpers should include defaults plus overrides and render CLI args."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            gm_project = workspace / "game"
            gm_project.mkdir()
            os.environ["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"] = "45"
            try:
                env = _build_codex_env(gm_project_root=gm_project, workspace_root=workspace)
                self.assertEqual(
                    env["GM_PROJECT_ROOT"],
                    str(gm_project),
                )
                self.assertEqual(env["PYTHONUNBUFFERED"], "1")
                self.assertEqual(env["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"], "45")

                env_args = _build_codex_env_args(env)
                self.assertIn("GM_PROJECT_ROOT=", env_args)
                self.assertIn("PYTHONUNBUFFERED=1", env_args)
                self.assertIn("GMS_MCP_DEFAULT_TIMEOUT_SECONDS=45", env_args)
            finally:
                del os.environ["GMS_MCP_DEFAULT_TIMEOUT_SECONDS"]

    def test_generate_codex_config_dry_run(self):
        """Dry run should not create files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            gm_project = workspace / "gamemaker"
            gm_project.mkdir()

            path, payload, merged = _generate_codex_config(
                workspace_root=workspace,
                output_path=workspace / ".codex" / "mcp.toml",
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                gm_project_root=gm_project,
                dry_run=True,
            )

            self.assertEqual(path, workspace / ".codex" / "mcp.toml")
            self.assertIn("[mcp_servers.gms]", payload)
            self.assertIn("[mcp_servers.gms]", merged)
            self.assertFalse(path.exists())

    def test_generate_codex_config_writes_file(self):
        """Real run should write the config payload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            gm_project = workspace / "gamemaker"
            gm_project.mkdir()

            path, payload, merged = _generate_codex_config(
                workspace_root=workspace,
                output_path=workspace / ".codex" / "mcp.toml",
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                gm_project_root=gm_project,
                dry_run=False,
            )

            self.assertTrue(path.exists())
            on_disk = path.read_text(encoding="utf-8")
            self.assertEqual(payload + "\n", on_disk)
            self.assertEqual(on_disk, merged)

    def test_upsert_codex_server_config(self):
        """Merging should preserve unrelated sections and replace matching server blocks."""
        existing = "\n".join(
            [
                "[mcp_servers.other]",
                'command = "old"',
                "",
                "[mcp_servers.other.env]",
                'VALUE = "old"',
                "",
                "[mcp_servers.shared]",
                'command = "shared"',
                "",
                "[mcp_servers.shared.env]",
            ]
        )

        replacement = "\n".join(
            [
                "[mcp_servers.shared]",
                'command = "gms-mcp"',
                'args = []',
                "",
                "[mcp_servers.shared.env]",
                "GM_PROJECT_ROOT = \"/workspace\"",
            ]
        )

        merged = _upsert_codex_server_config(
            existing_text=existing,
            server_name="shared",
            server_block=replacement,
        )

        # Existing unrelated server remains.
        self.assertIn("[mcp_servers.other]", merged)
        self.assertIn('command = "old"', merged)
        # Server block replaced.
        first = merged.find("[mcp_servers.shared]")
        self.assertNotEqual(first, -1)
        after_shared = merged[first : merged.find("[mcp_servers", first + 1)]
        self.assertNotIn("command = \"old\"", after_shared)
        self.assertIn('command = "gms-mcp"', merged)
        self.assertIn("GM_PROJECT_ROOT = \"/workspace\"", merged)

    def test_generate_codex_config_merge_existing_file(self):
        """Existing mcp.toml entries should be preserved when writing Codex config."""
        self._require_toml_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            gm_project = workspace / "gamemaker"
            gm_project.mkdir()
            config_path = workspace / ".codex" / "mcp.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        "[mcp_servers.other]",
                        'command = "old"',
                        "",
                        "[mcp_servers.other.env]",
                        'VALUE = "test"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            path, payload, _ = _generate_codex_config(
                workspace_root=workspace,
                output_path=config_path,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                gm_project_root=gm_project,
                dry_run=False,
            )

            on_disk = path.read_text(encoding="utf-8")
            self.assertIn("[mcp_servers.other]", on_disk)
            self.assertIn("[mcp_servers.gms]", on_disk)
            self.assertEqual(on_disk.count("[mcp_servers.gms]"), 1)
            self.assertIn(payload, on_disk)

    def test_generate_codex_config_invalid_existing_toml_raises(self):
        """Malformed existing TOML should fail fast before merge/write."""
        self._require_toml_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            gm_project = workspace / "gamemaker"
            gm_project.mkdir()
            config_path = workspace / ".codex" / "mcp.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "\n".join(
                    [
                        "[mcp_servers.other]",
                        'command = "broken',
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                _generate_codex_config(
                    workspace_root=workspace,
                    output_path=config_path,
                    server_name="gms",
                    command="gms-mcp",
                    args_prefix=[],
                    gm_project_root=gm_project,
                    dry_run=True,
                )

    def test_generate_codex_config_global_excludes_project_root(self):
        """Global mode payload should not include a fixed GM_PROJECT_ROOT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            gm_project = workspace / "gamemaker"
            gm_project.mkdir()
            path, payload, _ = _generate_codex_config(
                workspace_root=workspace,
                output_path=workspace / ".codex" / "config.toml",
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                gm_project_root=gm_project,
                dry_run=False,
                include_project_root=False,
            )

            on_disk = path.read_text(encoding="utf-8")
            self.assertNotIn("GM_PROJECT_ROOT", on_disk)
            self.assertIn('[mcp_servers.gms]', on_disk)
            self.assertIn('"gms-mcp"', on_disk)

    def test_parse_toml_or_raise_and_validate_sections(self):
        """TOML parser + section validator should accept well-formed mcp sections."""
        self._require_toml_parser()
        text = "\n".join(
            [
                "[mcp_servers.gms]",
                'command = "gms-mcp"',
                "args = []",
                "",
                "[mcp_servers.gms.env]",
                'PYTHONUNBUFFERED = "1"',
            ]
        )
        parsed = _parse_toml_or_raise(text=text, source_label="inline")
        _validate_codex_sections(parsed=parsed, source_label="inline", server_name="gms")

    def test_main_codex_dry_run(self):
        """CLI dry-run for --codex reports payload and does not write files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            buffer = io.StringIO()

            with redirect_stdout(buffer):
                ret = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--codex",
                        "--server-name",
                        "gms-codex",
                        "--dry-run",
                    ]
                )

            output = buffer.getvalue()
            self.assertEqual(ret, 0)
            self.assertIn("[DRY-RUN] Codex config would be written to:", output)
            self.assertFalse((workspace / ".codex" / "mcp.toml").exists())

    def test_main_codex_dry_run_only_prints_final_payloads(self):
        """--codex-dry-run-only should print final merged payloads for local + global targets."""
        self._require_toml_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            home_dir = Path(tmpdir) / "home"
            with temporary_home(home_dir):
                global_path = home_dir / ".codex" / "config.toml"
                global_path.parent.mkdir(parents=True, exist_ok=True)
                global_path.write_text(
                    "\n".join(
                        [
                            "[mcp_servers.existing]",
                            'command = "existing-cmd"',
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    ret = main(
                        [
                            "--workspace-root",
                            str(workspace),
                            "--non-interactive",
                            "--server-name",
                            "gms-preview",
                            "--codex-dry-run-only",
                        ]
                    )
                output = buffer.getvalue()
                self.assertEqual(ret, 0)
                self.assertIn("[DRY-RUN] Codex final merged payload:", output)
                self.assertIn("[DRY-RUN] Codex global final merged payload:", output)
                self.assertIn("[DRY-RUN] Codex dry-run-only mode complete.", output)
                self.assertFalse((workspace / ".codex" / "mcp.toml").exists())

    def test_main_codex_global_merges_into_home(self):
        """--codex-global writes (and merges) the shared ~/.codex/config.toml entry."""
        self._require_toml_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            home_dir = Path(tmpdir) / "home"
            with temporary_home(home_dir):
                codex_global = home_dir / ".codex" / "config.toml"
                codex_global.parent.mkdir(parents=True, exist_ok=True)
                codex_global.write_text(
                    "\n".join(
                        [
                            "[mcp_servers.other]",
                            'command = "existing"',
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    ret = main(
                        [
                            "--workspace-root",
                            str(workspace),
                            "--non-interactive",
                            "--codex-global",
                            "--server-name",
                            "gms-global",
                        ]
                    )

                self.assertEqual(ret, 0)
                on_disk = codex_global.read_text(encoding="utf-8")
                self.assertIn("[mcp_servers.other]", on_disk)
                self.assertIn("[mcp_servers.gms-global]", on_disk)
                self.assertEqual(on_disk.count("[mcp_servers.gms-global]"), 1)
                self.assertNotIn("GM_PROJECT_ROOT", on_disk)

    def test_main_codex_check_reports_active_entry(self):
        """--codex-check should report paths and the active server source/entry."""
        self._require_toml_parser()
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "project.yyp").touch()
            local_codex = workspace / ".codex" / "mcp.toml"
            local_codex.parent.mkdir(parents=True, exist_ok=True)
            local_codex.write_text(
                "\n".join(
                    [
                        "[mcp_servers.gms-check]",
                        'command = "gms-mcp"',
                        "args = []",
                        "",
                        "[mcp_servers.gms-check.env]",
                        'PYTHONUNBUFFERED = "1"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                ret = main(
                    [
                        "--workspace-root",
                        str(workspace),
                        "--non-interactive",
                        "--server-name",
                        "gms-check",
                        "--codex-check",
                    ]
                )
            output = buffer.getvalue()
            self.assertEqual(ret, 0)
            self.assertIn("[INFO] Codex workspace config:", output)
            self.assertIn("[INFO] Active server entry 'gms-check' source:", output)
            self.assertIn('"command": "gms-mcp"', output)

    def test_generate_claude_code_plugin_dry_run(self):
        """Dry run should not create files but return paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "test-plugin"

            written = _generate_claude_code_plugin(
                plugin_dir=plugin_dir,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=True,
            )

            # Should return expected paths
            self.assertEqual(len(written), 2)
            self.assertTrue(any(".claude-plugin" in str(p) for p in written))
            self.assertTrue(any(".mcp.json" in str(p) for p in written))

            # But files should NOT exist (dry run)
            self.assertFalse(plugin_dir.exists())

    def test_generate_claude_code_plugin_creates_files(self):
        """Plugin generation should create correct file structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = Path(tmpdir) / "gms-mcp"

            written = _generate_claude_code_plugin(
                plugin_dir=plugin_dir,
                server_name="gms",
                command="gms-mcp",
                args_prefix=[],
                dry_run=False,
            )

            # Files should exist
            manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
            mcp_config_path = plugin_dir / ".mcp.json"

            self.assertTrue(manifest_path.exists())
            self.assertTrue(mcp_config_path.exists())

            # Validate manifest content
            with open(manifest_path) as f:
                manifest = json.load(f)
            self.assertEqual(manifest["name"], "gms-mcp")

            # Validate MCP config content
            with open(mcp_config_path) as f:
                mcp_config = json.load(f)
            self.assertIn("gms", mcp_config)
            self.assertEqual(mcp_config["gms"]["env"]["GM_PROJECT_ROOT"], "${CLAUDE_PROJECT_DIR}")


if __name__ == "__main__":
    unittest.main()
