#!/usr/bin/env python3
"""Coverage tests for gms_helpers.install."""

from __future__ import annotations

import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from gms_helpers import install as install_module


def _capture_output(func, *args, **kwargs):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


class _FakeWinReg(types.SimpleNamespace):
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_EXPAND_SZ = 3

    def __init__(self):
        super().__init__()
        self.path_value = ""
        self.set_calls = []

    class _KeyCtx:
        def __init__(self, owner, mode):
            self.owner = owner
            self.mode = mode

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def OpenKey(self, root, path, reserved, mode):
        return self._KeyCtx(self, mode)

    def QueryValueEx(self, key, name):
        if not self.path_value:
            raise FileNotFoundError(name)
        return self.path_value, self.REG_EXPAND_SZ

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.path_value = value
        self.set_calls.append((name, value_type, value))


class TestInstallWrapperCoverage(unittest.TestCase):
    def test_unix_install_success_and_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            local_bin = home / ".local" / "bin"
            local_bin.mkdir(parents=True)

            with patch("gms_helpers.install.platform.system", return_value="Linux"), patch(
                "gms_helpers.install.Path.home", return_value=home
            ), patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=False):
                result, output = _capture_output(install_module.install_gms_command, auto=False)

            self.assertTrue(result)
            target = local_bin / "gms"
            self.assertTrue(target.exists())
            self.assertIn('python3 "', target.read_text(encoding="utf-8"))
            self.assertIn("Installed gms command", output)
            self.assertIn("Add this to your shell configuration", output)

        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            with patch("gms_helpers.install.platform.system", return_value="Linux"), patch(
                "gms_helpers.install.Path.home", return_value=home
            ), patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=False):
                result, output = _capture_output(install_module.install_gms_command, auto=False)

            self.assertTrue(result)
            self.assertIn("Could not auto-install. Manual options", output)

    def test_windows_install_creates_shim_and_handles_auto_path_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            localapp = Path(temp_dir) / "LocalAppData"
            windows_apps = localapp / "Microsoft" / "WindowsApps"
            windows_apps.mkdir(parents=True)
            fake_winreg = _FakeWinReg()

            with patch("gms_helpers.install.platform.system", return_value="Windows"), patch.dict(
                "os.environ",
                {"LOCALAPPDATA": str(localapp)},
                clear=False,
            ), patch.dict(sys.modules, {"winreg": fake_winreg}):
                result, output = _capture_output(install_module.install_gms_command, auto=True)

            self.assertTrue(result)
            shim = windows_apps / "gms.cmd"
            self.assertTrue(shim.exists())
            self.assertIn(str(install_module.Path(__file__).parents[3] / "src" / "gms_helpers" / "gms.py").split("gms-mcp")[0], shim.read_text(encoding="utf-8"))
            self.assertIn("Shim created", output)
            self.assertIn("Added to user PATH", output)
            self.assertTrue(fake_winreg.set_calls)

    def test_windows_install_without_windows_apps_shows_warning_and_profile_tip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            localapp = Path(temp_dir) / "MissingLocalAppData"
            with patch("gms_helpers.install.platform.system", return_value="Windows"), patch.dict(
                "os.environ",
                {"LOCALAPPDATA": str(localapp)},
                clear=False,
            ):
                result, output = _capture_output(install_module.install_gms_command, auto=False)

            self.assertTrue(result)
            self.assertIn("WindowsApps not found", output)
            self.assertIn("PowerShell profile", output)

    def test_parse_args_and_run_exits_with_install_result(self):
        argv_backup = sys.argv[:]
        try:
            sys.argv = ["install", "--auto"]
            with patch("gms_helpers.install.install_gms_command", return_value=True):
                with self.assertRaises(SystemExit) as exc:
                    install_module._parse_args_and_run()
            self.assertEqual(exc.exception.code, 0)

            sys.argv = ["install"]
            with patch("gms_helpers.install.install_gms_command", return_value=False):
                with self.assertRaises(SystemExit) as exc:
                    install_module._parse_args_and_run()
            self.assertEqual(exc.exception.code, 1)
        finally:
            sys.argv = argv_backup


if __name__ == "__main__":
    unittest.main()
