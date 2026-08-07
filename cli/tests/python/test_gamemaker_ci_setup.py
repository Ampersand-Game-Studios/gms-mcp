from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import scripts.setup_gamemaker_ci as setup_ci


class TestGameMakerCISetup(unittest.TestCase):
    def test_detects_each_approved_host_architecture(self):
        cases = (
            ("Darwin", "arm64", "macos", "mac,base-module-osx-arm64"),
            ("Windows", "AMD64", "windows", "windows,base-module-windows-x64"),
            ("Linux", "x86_64", "linux", "linux,base-module-linux-x64"),
        )
        for system, machine, slug, modules in cases:
            with self.subTest(system=system, machine=machine):
                with (
                    mock.patch.object(setup_ci.platform, "system", return_value=system),
                    mock.patch.object(setup_ci.platform, "machine", return_value=machine),
                ):
                    config = setup_ci.detect_host_config()
                self.assertEqual(config.slug, slug)
                self.assertEqual(config.modules, modules)

    def test_rejects_unapproved_host_and_runtime(self):
        with (
            mock.patch.object(setup_ci.platform, "system", return_value="Darwin"),
            mock.patch.object(setup_ci.platform, "machine", return_value="x86_64"),
        ):
            with self.assertRaisesRegex(setup_ci.SetupError, "unsupported disposable runner"):
                setup_ci.detect_host_config()

        with self.assertRaisesRegex(setup_ci.SetupError, "unapproved GameMaker runtime"):
            setup_ci.install_runtime("2099.1.2.3")

    def test_missing_environment_secret_fails_before_installation(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(setup_ci.SetupError, "GAMEMAKER_ACCESS_KEY secret is unavailable"):
                setup_ci.install_runtime("2024.14.4.268")

    def test_zip_extraction_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "unsafe.zip"
            destination = root / "extract"
            destination.mkdir()
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../escaped.txt", "private")

            with self.assertRaisesRegex(setup_ci.SetupError, "unsafe path"):
                setup_ci._extract_verified_zip(archive, destination)

            self.assertFalse((root / "escaped.txt").exists())

    def test_cleanup_deletes_license_directory_and_clears_exported_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_dir = root / "gms-mcp-gamemaker-user"
            user_dir.mkdir()
            (user_dir / "licence.plist").write_text("private", encoding="utf-8")
            github_env = root / "github-env"
            github_env.touch()

            with mock.patch.dict(
                os.environ,
                {"RUNNER_TEMP": str(root), "GITHUB_ENV": str(github_env)},
            ):
                setup_ci.cleanup_ephemeral_license()

            self.assertFalse(user_dir.exists())
            self.assertEqual(github_env.read_text(encoding="utf-8"), "GMS_MCP_LICENSE_FILE=\n")

    def test_github_environment_writer_rejects_newlines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            github_env = Path(temp_dir) / "github-env"
            github_env.touch()
            with self.assertRaisesRegex(setup_ci.SetupError, "unsafe GitHub environment"):
                setup_ci._append_github_env(github_env, {"GMS_MCP_RUNTIME_ROOT": "safe\nINJECTED=true"})

    @unittest.skipIf(os.name == "nt", "Linux runtime symlink finalization requires POSIX symlinks")
    def test_linux_finalization_targets_only_installed_x64_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            igor_dir = runtime / "bin/igor/linux/x64"
            asset_compiler = runtime / "bin/assetcompiler/linux/x64/GMAssetCompiler"
            web_server = runtime / "bin/webserver/linux/x64/GMWebServer"
            for executable in (igor_dir / "Igor", asset_compiler, web_server):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("binary", encoding="utf-8")

            setup_ci._finalize_linux_runtime(runtime)

            self.assertEqual(os.readlink(igor_dir / "FiltersAndEffects"), "../../../FiltersAndEffects")
            self.assertEqual(os.readlink(igor_dir / "ParticleImages"), "../../../assetcompiler/ParticleImages")
            self.assertTrue((igor_dir / "FiltersAndEffects").is_symlink())
            self.assertTrue(os.access(igor_dir / "Igor", os.X_OK))
            self.assertTrue(os.access(asset_compiler, os.X_OK))


if __name__ == "__main__":
    unittest.main()
