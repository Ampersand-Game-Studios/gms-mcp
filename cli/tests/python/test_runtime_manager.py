import unittest
from unittest import mock
from pathlib import Path
import tempfile
import json
import os
import platform
from gms_helpers.runtime_manager import RuntimeManager, RuntimeInfo

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
        
        with mock.patch.object(RuntimeManager, 'list_installed') as mock_list:
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
        
        with mock.patch.object(RuntimeManager, 'list_installed') as mock_list:
            mock_list.return_value = [r2, r1] # Sorted newest first
            
            # Default select newest
            selected = self.manager.select()
            self.assertEqual(selected.version, "2.0.0.0")
            
            # Select with override
            selected = self.manager.select("1.0.0.0")
            self.assertEqual(selected.version, "1.0.0.0")
            
            # Select with pin
            with mock.patch.object(RuntimeManager, 'get_pinned') as mock_pin:
                mock_pin.return_value = "1.0.0.0"
                selected = self.manager.select()
                self.assertEqual(selected.version, "1.0.0.0")

    def test_list_installed_discovers_apple_silicon_igor(self):
        runtime_root = self.project_root / "Library/Application Support/GameMakerStudio2/Cache/runtimes/runtime-2026.1.1.0.1"
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

if __name__ == '__main__':
    unittest.main()
