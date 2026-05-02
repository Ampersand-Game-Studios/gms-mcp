import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import asyncio
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gms_helpers import gms as gms_module
from gms_mcp.server.direct import _run_gms_inprocess
from gms_mcp.server.subprocess_runner import _run_cli_async
from gms_mcp.telemetry import (
    SUPPRESS_CLI_TELEMETRY_ENV_VAR,
    clear_spool,
    count_spool_events,
    enable_telemetry,
    flush_spool,
    load_config,
    prompt_for_consent,
    queue_event,
    resolve_state,
)


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


class _FakeResponse:
    status = 202
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _create_basic_gamemaker_project(project_root: Path, *, name: str = "TestProject") -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    for directory_name in ("objects", "sprites", "scripts", "rooms", "texturegroups"):
        (project_root / directory_name).mkdir(parents=True, exist_ok=True)

    yyp_path = project_root / f"{name}.yyp"
    yyp_path.write_text(
        json.dumps(
            {
                "$GMProject": "",
                "%Name": name,
                "name": name,
                "resources": [],
                "folders": [],
                "resourceType": "GMProject",
                "resourceVersion": "2.0",
                "configs": {"name": "Default", "children": [{"name": "desktop", "children": []}]},
                "TextureGroups": [
                    {
                        "$GMTextureGroup": "",
                        "%Name": "Default",
                        "name": "Default",
                        "resourceType": "GMTextureGroup",
                        "resourceVersion": "2.0",
                        "ConfigValues": {},
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return yyp_path


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[3]
        self.python_exe = sys.executable
        self.temp_dir = tempfile.mkdtemp()
        self.home_dir = Path(self.temp_dir) / "home"
        self.home_dir.mkdir(parents=True)
        self.work_dir = Path(self.temp_dir) / "workspace"
        self.work_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _telemetry_env(self) -> dict[str, str]:
        env = {**os.environ, "PYTHONPATH": str(self.repo_root / "src"), "HOME": str(self.home_dir), "USERPROFILE": str(self.home_dir)}
        env["PYTEST_CURRENT_TEST"] = ""
        env["GMS_TEST_SUITE"] = ""
        env["CI"] = ""
        env["GITHUB_ACTIONS"] = ""
        return env

    def test_enable_with_install_hash_persists_config(self):
        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ):
            config = enable_telemetry(include_install_hash=True)
            state = resolve_state()

        self.assertEqual(config.consent, "enabled")
        self.assertTrue(config.include_install_hash)
        self.assertTrue(config.install_hash)
        self.assertTrue(state.enabled)
        self.assertTrue(state.include_install_hash)

    def test_prompt_for_consent_blank_persists_disabled(self):
        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ), patch("builtins.input", return_value=""):
            enabled = prompt_for_consent()
            config = load_config()

        self.assertFalse(enabled)
        self.assertEqual(config.consent, "disabled")
        self.assertFalse(config.include_install_hash)

    def test_flush_spool_uploads_and_clears_events(self):
        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ), patch("urllib.request.urlopen", return_value=_FakeResponse()):
            state = enable_telemetry(include_install_hash=False)
            queued = queue_event(
                state=resolve_state(),
                surface="cli",
                event_type="cli.command",
                action="telemetry.test",
                tool_name="telemetry.test",
                tool_family="telemetry",
                result="ok",
                duration_ms=1,
                execution_mode="inline",
            )
            result = flush_spool(force=True)
            remaining = count_spool_events()

        self.assertTrue(state.consent == "enabled")
        self.assertTrue(queued)
        self.assertTrue(result.ok)
        self.assertEqual(result.sent_events, 1)
        self.assertEqual(remaining, 0)

    def test_clear_spool_removes_queued_events(self):
        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ):
            enable_telemetry(include_install_hash=False)
            queue_event(
                state=resolve_state(),
                surface="cli",
                event_type="cli.command",
                action="telemetry.test",
                tool_name="telemetry.test",
                tool_family="telemetry",
                result="ok",
                duration_ms=1,
                execution_mode="inline",
            )
            removed = clear_spool()
            remaining = count_spool_events()

        self.assertEqual(removed, 1)
        self.assertEqual(remaining, 0)

    def test_gms_telemetry_status_does_not_require_project(self):
        result = subprocess.run(
            [self.python_exe, "-m", "gms_helpers.gms", "telemetry", "status"],
            cwd=str(self.work_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self._telemetry_env(),
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Consent:", result.stdout)

    def test_gms_prompts_once_after_successful_interactive_run(self):
        fake_stdin = SimpleNamespace(isatty=lambda: True)
        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ), patch.object(gms_module.sys, "stdin", fake_stdin), patch.object(
            gms_module.sys,
            "argv",
            ["gms", "skills", "list"],
        ), patch("builtins.input", return_value="n") as prompt_mock, redirect_stdout(io.StringIO()):
            first = gms_module.main()
            first_config = load_config()

        self.assertTrue(first)
        self.assertEqual(prompt_mock.call_count, 1)
        self.assertEqual(first_config.consent, "disabled")

        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ), patch.object(gms_module.sys, "stdin", fake_stdin), patch.object(
            gms_module.sys,
            "argv",
            ["gms", "skills", "list"],
        ), patch("builtins.input", side_effect=AssertionError("prompt should not repeat")), redirect_stdout(io.StringIO()):
            second = gms_module.main()

        self.assertTrue(second)

    def test_gms_main_restores_cwd_after_project_command(self):
        project_root = self.work_dir / "project"
        _create_basic_gamemaker_project(project_root)
        original_cwd = Path.cwd()

        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {
                "PYTEST_CURRENT_TEST": "",
                "GMS_TEST_SUITE": "",
                "CI": "",
                "GITHUB_ACTIONS": "",
                SUPPRESS_CLI_TELEMETRY_ENV_VAR: "1",
            },
            clear=False,
        ), patch.object(
            gms_module.sys,
            "argv",
            ["gms", "--project-root", str(project_root), "maintenance", "validate-json"],
        ), redirect_stdout(io.StringIO()):
            result = gms_module.main()

        self.assertTrue(result)
        self.assertEqual(Path.cwd(), original_cwd)

    def test_nested_cli_suppression_skips_prompt(self):
        fake_stdin = SimpleNamespace(isatty=lambda: True)
        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {
                "PYTEST_CURRENT_TEST": "",
                "GMS_TEST_SUITE": "",
                "CI": "",
                "GITHUB_ACTIONS": "",
                SUPPRESS_CLI_TELEMETRY_ENV_VAR: "1",
            },
            clear=False,
        ), patch.object(gms_module.sys, "stdin", fake_stdin), patch.object(
            gms_module.sys,
            "argv",
            ["gms", "skills", "list"],
        ), patch("builtins.input", side_effect=AssertionError("nested CLI should not prompt")), redirect_stdout(io.StringIO()):
            result = gms_module.main()

        self.assertTrue(result)
        self.assertFalse((self.home_dir / ".gms-mcp" / "telemetry.json").exists())

    def test_run_gms_inprocess_suppresses_cli_telemetry(self):
        project_root = self.work_dir / "project"
        _create_basic_gamemaker_project(project_root)

        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ):
            enable_telemetry(include_install_hash=False)
            result = _run_gms_inprocess(["telemetry", "status"], str(project_root))
            queued_events = count_spool_events()

        self.assertTrue(result.ok)
        self.assertEqual(queued_events, 0)

    def test_run_cli_async_suppresses_cli_telemetry(self):
        project_root = self.work_dir / "project"
        _create_basic_gamemaker_project(project_root)

        with temporary_home(self.home_dir), patch.dict(
            os.environ,
            {"PYTEST_CURRENT_TEST": "", "GMS_TEST_SUITE": "", "CI": "", "GITHUB_ACTIONS": ""},
            clear=False,
        ):
            enable_telemetry(include_install_hash=False)
            result = asyncio.run(
                _run_cli_async(
                    ["telemetry", "status"],
                    str(project_root),
                    timeout_seconds=10,
                    tool_name="gm_cli",
                )
            )
            queued_events = count_spool_events()

        self.assertTrue(result.ok, msg=result.error or result.stderr or result.stdout)
        self.assertEqual(queued_events, 0)
