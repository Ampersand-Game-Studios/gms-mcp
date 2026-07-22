import unittest
from unittest import mock
from pathlib import Path
import tempfile
import json
import os
import platform
from gms_helpers.runtime_manager import RuntimeManager, RuntimeInfo, _runtime_sort_key, classify_runtime_channel
from gms_helpers.runner_support.discovery import RunnerDiscoveryMixin


class TestRuntimeManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp_dir.name)
        self.manager = RuntimeManager(self.project_root)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_pin_unpin(self):
        # Create a dummy runtime so we can pin it
        # Note: RuntimeManager.pin validates version exists via list_installed
        # We might need to mock list_installed or create a dummy runtime folder

        runtime_path = self.project_root / "dummy_runtimes" / "runtime-2024.1.1.1"
        runtime_path.mkdir(parents=True)
        # Create dummy Igor
        igor_dir = runtime_path / "bin/igor/windows/x64"
        igor_dir.mkdir(parents=True)
        (igor_dir / "Igor.exe").touch()

        # Mock possible paths to include our dummy
        import gms_helpers.runtime_manager as rm

        old_paths = rm.platform.system
        # This is getting complex, let's just mock list_installed

        with mock.patch.object(RuntimeManager, "list_installed") as mock_list:
            mock_list.return_value = [
                RuntimeInfo("2024.1.1.1", str(runtime_path), str(igor_dir / "Igor.exe"), True, "stable")
            ]

            # Pin
            success = self.manager.pin("2024.1.1.1")
            self.assertTrue(success)
            self.assertEqual(self.manager.get_pinned(), "2024.1.1.1")

            # Unpin
            success = self.manager.unpin()
            self.assertTrue(success)
            self.assertIsNone(self.manager.get_pinned())

    def test_select_logic(self):
        r1 = RuntimeInfo("1.0.0.0", "/path/1", "/path/1/Igor.exe", True, "stable")
        r2 = RuntimeInfo("2.0.0.0", "/path/2", "/path/2/Igor.exe", True, "stable")

        with mock.patch.object(RuntimeManager, "list_installed") as mock_list:
            mock_list.return_value = [r2, r1]  # Sorted newest first

            # Default select newest
            selected = self.manager.select()
            self.assertEqual(selected.version, "2.0.0.0")

            # Select with override
            selected = self.manager.select("1.0.0.0")
            self.assertEqual(selected.version, "1.0.0.0")

            # Select with pin
            with mock.patch.object(RuntimeManager, "get_pinned") as mock_pin:
                mock_pin.return_value = "1.0.0.0"
                selected = self.manager.select()
                self.assertEqual(selected.version, "1.0.0.0")

    def test_select_matches_project_channel_and_defaults_to_stable(self):
        stable = RuntimeInfo("2024.14.4.268", "/stable", "/stable/Igor", True, "stable")
        lts = RuntimeInfo("2026.0.0.23", "/lts", "/lts/Igor", True, "lts")

        with mock.patch.object(RuntimeManager, "list_installed", return_value=[lts, stable]):
            self.assertEqual(self.manager.select(), stable)

            (self.project_root / "TestGame.yyp").write_text(
                '{"MetaData":{"IDEVersion":"2026.0.1.20"}}',
                encoding="utf-8",
            )
            self.assertEqual(self.manager.select(), lts)

    def test_classify_runtime_channel_handles_lts2026_and_beta_series(self):
        self.assertEqual(classify_runtime_channel("2026.0.0.23"), "lts")
        self.assertEqual(classify_runtime_channel("runtime-2026.0.0.23"), "lts")
        self.assertEqual(classify_runtime_channel("2022.0.3.80"), "lts")
        self.assertEqual(classify_runtime_channel("2.3.7.606"), "lts")
        self.assertEqual(classify_runtime_channel("2024.1400.5.12"), "beta")
        self.assertEqual(classify_runtime_channel("2024.14.4.268"), "stable")
        self.assertEqual(classify_runtime_channel(""), "unknown")

    def test_list_installed_discovers_apple_silicon_igor(self):
        runtime_root = (
            self.project_root
            / "Library/Application Support/GameMakerStudio2-LTS2026/Cache/runtimes/runtime-2026.1.1.0.1"
        )
        igor_file = runtime_root / "bin/igor/osx/arm64/Igor"
        igor_file.parent.mkdir(parents=True, exist_ok=True)
        igor_file.write_text("binary")

        with (
            mock.patch.object(platform, "system", return_value="Darwin"),
            mock.patch.object(Path, "home", return_value=self.project_root),
        ):
            manager = RuntimeManager(self.project_root)
            runtimes = manager.list_installed()

        self.assertTrue(any(runtime.version == "2026.1.1.0.1" and runtime.is_valid for runtime in runtimes))
        self.assertTrue(
            any(runtime.version == "2026.1.1.0.1" and runtime.release_channel == "lts" for runtime in runtimes)
        )

    def test_explicit_runtime_root_is_authoritative(self):
        explicit_root = self.project_root / "ephemeral-runtimes"
        runtime_root = explicit_root / "runtime-2024.14.4.268"
        igor_file = runtime_root / "bin/igor/osx/arm64/Igor"
        igor_file.parent.mkdir(parents=True)
        igor_file.write_text("binary", encoding="utf-8")

        with (
            mock.patch.object(platform, "system", return_value="Darwin"),
            mock.patch.dict(os.environ, {"GMS_MCP_RUNTIME_ROOT": str(explicit_root)}),
        ):
            runtimes = RuntimeManager(self.project_root).list_installed()

        self.assertEqual([runtime.version for runtime in runtimes], ["2024.14.4.268"])

    def test_invalid_explicit_runtime_root_fails_closed(self):
        standard_root = (
            self.project_root / "Library/Application Support/GameMakerStudio2/Cache/runtimes/runtime-2024.14.4.268"
        )
        igor_file = standard_root / "bin/igor/osx/arm64/Igor"
        igor_file.parent.mkdir(parents=True)
        igor_file.write_text("binary", encoding="utf-8")

        with (
            mock.patch.object(platform, "system", return_value="Darwin"),
            mock.patch.object(Path, "home", return_value=self.project_root),
            mock.patch.dict(
                os.environ,
                {"GMS_MCP_RUNTIME_ROOT": str(self.project_root / "missing")},
            ),
        ):
            runtimes = RuntimeManager(self.project_root).list_installed()

        self.assertEqual(runtimes, [])

    def test_runtime_versions_sort_numerically(self):
        versions = ["2024.9.1.10", "2024.14.4.268", "2026.0.0.23"]

        self.assertEqual(
            sorted(versions, key=_runtime_sort_key, reverse=True), ["2026.0.0.23", "2024.14.4.268", "2024.9.1.10"]
        )

    def test_selected_lts_runtime_prefers_matching_prefabs_and_license_family(self):
        install_root = self.project_root / "Shared" / "GameMakerStudio2-LTS2026"
        runtime_path = install_root / "Cache" / "runtimes" / "runtime-2026.0.0.23"
        runtime_path.mkdir(parents=True)
        prefabs = install_root / "Prefabs"
        prefabs.mkdir()
        license_path = self.project_root / "Library/Application Support/GameMakerStudio2-LTS2026/user_1/licence.plist"
        license_path.parent.mkdir(parents=True)
        license_path.write_text("license", encoding="utf-8")

        discovery = RunnerDiscoveryMixin()
        discovery.runtime_path = runtime_path
        with (
            mock.patch.object(platform, "system", return_value="Darwin"),
            mock.patch.object(Path, "home", return_value=self.project_root),
        ):
            self.assertEqual(discovery.get_prefabs_path(), prefabs)
            self.assertEqual(discovery.find_license_file(), license_path)

    def test_explicit_license_file_is_authoritative(self):
        explicit_license = self.project_root / "ephemeral" / "licence.plist"
        explicit_license.parent.mkdir()
        explicit_license.write_text("license", encoding="utf-8")

        discovery = RunnerDiscoveryMixin()
        with mock.patch.dict(os.environ, {"GMS_MCP_LICENSE_FILE": str(explicit_license)}):
            self.assertEqual(discovery.find_license_file(), explicit_license)

        with mock.patch.dict(
            os.environ,
            {"GMS_MCP_LICENSE_FILE": str(self.project_root / "missing.plist")},
        ):
            self.assertIsNone(discovery.find_license_file())


if __name__ == "__main__":
    unittest.main()
