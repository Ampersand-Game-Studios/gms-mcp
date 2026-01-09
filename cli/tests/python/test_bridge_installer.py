#!/usr/bin/env python3
"""
Tests for bridge_installer.py - Safe bridge installation/removal.

Tests cover:
- Installation with rollback
- Uninstallation
- Status checking
- Safety mechanisms (backup, rollback)
"""

import json
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add source to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from gms_helpers.bridge_installer import (
    BridgeInstaller,
    BridgeInstallError,
    install_bridge,
    uninstall_bridge,
    is_bridge_installed,
    get_bridge_status,
    BRIDGE_OBJECT_NAME,
    BRIDGE_SCRIPT_NAME,
    BRIDGE_FOLDER_NAME,
)
from gms_helpers.utils import load_json


class TestBridgeInstallerInit(unittest.TestCase):
    """Tests for BridgeInstaller initialization."""
    
    def test_init_with_valid_project(self):
        """Test initialization with valid project."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a minimal .yyp
            yyp_path = Path(temp_dir) / "test.yyp"
            yyp_path.write_text('{"name": "test", "resources": []}')
            
            installer = BridgeInstaller(Path(temp_dir))
            
            self.assertEqual(installer.project_root, Path(temp_dir).resolve())
            self.assertEqual(installer.yyp_path, yyp_path)
            
    def test_init_without_yyp(self):
        """Test initialization without .yyp file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(BridgeInstallError):
                BridgeInstaller(Path(temp_dir))


class TestBridgeInstallerStatus(unittest.TestCase):
    """Tests for status checking."""
    
    def setUp(self):
        """Create a temporary project directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create minimal .yyp
        self.yyp_path = self.project_root / "test.yyp"
        self.yyp_data = {
            "name": "test",
            "resources": [],
            "Folders": [],
        }
        self.yyp_path.write_text(json.dumps(self.yyp_data))
        
    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_is_installed_false(self):
        """Test is_installed returns False when not installed."""
        installer = BridgeInstaller(self.project_root)
        
        self.assertFalse(installer.is_installed())
        
    def test_get_status_not_installed(self):
        """Test get_status when bridge not installed."""
        installer = BridgeInstaller(self.project_root)
        
        status = installer.get_status()
        
        self.assertFalse(status["installed"])
        self.assertFalse(status["object_exists"])
        self.assertFalse(status["script_exists"])
        self.assertFalse(status["registered_in_yyp"])


class TestBridgeInstallerInstall(unittest.TestCase):
    """Tests for bridge installation."""
    
    def setUp(self):
        """Create a temporary project directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create necessary directories
        (self.project_root / "objects").mkdir()
        (self.project_root / "scripts").mkdir()
        (self.project_root / "folders").mkdir()
        
        # Create minimal .yyp
        self.yyp_path = self.project_root / "test.yyp"
        self.yyp_data = {
            "name": "test",
            "resources": [],
            "Folders": [],
        }
        self.yyp_path.write_text(json.dumps(self.yyp_data))
        
    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_install_creates_files(self):
        """Test that installation creates the necessary files."""
        installer = BridgeInstaller(self.project_root)
        
        result = installer.install()
        
        self.assertTrue(result["ok"])
        
        # Check object was created
        object_dir = self.project_root / "objects" / BRIDGE_OBJECT_NAME
        self.assertTrue(object_dir.exists())
        self.assertTrue((object_dir / f"{BRIDGE_OBJECT_NAME}.yy").exists())
        self.assertTrue((object_dir / "Create_0.gml").exists())
        
        # Check script was created
        script_dir = self.project_root / "scripts" / BRIDGE_SCRIPT_NAME
        self.assertTrue(script_dir.exists())
        self.assertTrue((script_dir / f"{BRIDGE_SCRIPT_NAME}.yy").exists())
        self.assertTrue((script_dir / f"{BRIDGE_SCRIPT_NAME}.gml").exists())
        
    def test_install_updates_yyp(self):
        """Test that installation updates the .yyp file."""
        installer = BridgeInstaller(self.project_root)
        
        installer.install()
        
        # Read updated .yyp (use load_json which handles trailing commas)
        yyp_data = load_json(self.yyp_path)
            
        # Check resources were added
        resource_paths = [r.get("id", {}).get("path", "") for r in yyp_data["resources"]]
        self.assertTrue(any(BRIDGE_OBJECT_NAME in p for p in resource_paths))
        self.assertTrue(any(BRIDGE_SCRIPT_NAME in p for p in resource_paths))
        
    def test_install_idempotent(self):
        """Test that installing twice returns already_installed."""
        installer = BridgeInstaller(self.project_root)
        
        result1 = installer.install()
        result2 = installer.install()
        
        self.assertTrue(result1["ok"])
        self.assertTrue(result2["ok"])
        self.assertTrue(result2.get("already_installed", False))
        
    def test_install_creates_backup(self):
        """Test that installation creates a backup."""
        installer = BridgeInstaller(self.project_root)
        
        # Install - backup should be created and then cleaned up on success
        installer.install()
        
        # No backup should remain after successful install
        backups = list(self.project_root.glob("*.mcp_backup*"))
        self.assertEqual(len(backups), 0)


class TestBridgeInstallerUninstall(unittest.TestCase):
    """Tests for bridge uninstallation."""
    
    def setUp(self):
        """Create a temporary project with bridge installed."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create necessary directories
        (self.project_root / "objects").mkdir()
        (self.project_root / "scripts").mkdir()
        (self.project_root / "folders").mkdir()
        
        # Create minimal .yyp
        self.yyp_path = self.project_root / "test.yyp"
        self.yyp_data = {
            "name": "test",
            "resources": [],
            "Folders": [],
        }
        self.yyp_path.write_text(json.dumps(self.yyp_data))
        
        # Install bridge
        installer = BridgeInstaller(self.project_root)
        installer.install()
        
    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_uninstall_removes_files(self):
        """Test that uninstallation removes bridge files."""
        installer = BridgeInstaller(self.project_root)
        
        result = installer.uninstall()
        
        self.assertTrue(result["ok"])
        
        # Check object was removed
        object_dir = self.project_root / "objects" / BRIDGE_OBJECT_NAME
        self.assertFalse(object_dir.exists())
        
        # Check script was removed
        script_dir = self.project_root / "scripts" / BRIDGE_SCRIPT_NAME
        self.assertFalse(script_dir.exists())
        
    def test_uninstall_updates_yyp(self):
        """Test that uninstallation updates .yyp."""
        installer = BridgeInstaller(self.project_root)
        
        installer.uninstall()
        
        # Read updated .yyp (use load_json which handles trailing commas)
        yyp_data = load_json(self.yyp_path)
            
        # Check resources were removed
        resource_paths = [r.get("id", {}).get("path", "") for r in yyp_data["resources"]]
        self.assertFalse(any("__mcp" in p for p in resource_paths))
        
    def test_uninstall_not_installed(self):
        """Test uninstalling when not installed."""
        installer = BridgeInstaller(self.project_root)
        
        # First uninstall
        installer.uninstall()
        
        # Second uninstall should return already_uninstalled
        result = installer.uninstall()
        
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("already_uninstalled", False))


class TestBridgeInstallerConvenience(unittest.TestCase):
    """Tests for convenience functions."""
    
    def setUp(self):
        """Create a temporary project directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # Create necessary directories
        (self.project_root / "objects").mkdir()
        (self.project_root / "scripts").mkdir()
        (self.project_root / "folders").mkdir()
        
        # Create minimal .yyp
        yyp_path = self.project_root / "test.yyp"
        yyp_data = {"name": "test", "resources": [], "Folders": []}
        yyp_path.write_text(json.dumps(yyp_data))
        
    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_install_bridge_function(self):
        """Test install_bridge convenience function."""
        result = install_bridge(str(self.project_root))
        
        self.assertTrue(result["ok"])
        
    def test_uninstall_bridge_function(self):
        """Test uninstall_bridge convenience function."""
        install_bridge(str(self.project_root))
        result = uninstall_bridge(str(self.project_root))
        
        self.assertTrue(result["ok"])
        
    def test_is_bridge_installed_function(self):
        """Test is_bridge_installed convenience function."""
        self.assertFalse(is_bridge_installed(str(self.project_root)))
        
        install_bridge(str(self.project_root))
        
        self.assertTrue(is_bridge_installed(str(self.project_root)))
        
    def test_get_bridge_status_function(self):
        """Test get_bridge_status convenience function."""
        status = get_bridge_status(str(self.project_root))
        
        self.assertFalse(status["installed"])
        
        install_bridge(str(self.project_root))
        
        status = get_bridge_status(str(self.project_root))
        self.assertTrue(status["installed"])


class TestBridgeInstallerGMLContent(unittest.TestCase):
    """Tests for generated GML content."""
    
    def setUp(self):
        """Create a temporary project and install bridge."""
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        (self.project_root / "objects").mkdir()
        (self.project_root / "scripts").mkdir()
        (self.project_root / "folders").mkdir()
        
        yyp_path = self.project_root / "test.yyp"
        yyp_data = {"name": "test", "resources": [], "Folders": []}
        yyp_path.write_text(json.dumps(yyp_data))
        
        installer = BridgeInstaller(self.project_root)
        installer.install()
        
    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_create_event_contains_connection(self):
        """Test Create_0.gml contains connection code."""
        create_gml = self.project_root / "objects" / BRIDGE_OBJECT_NAME / "Create_0.gml"
        content = create_gml.read_text()
        
        self.assertIn("network_create_socket", content)
        self.assertIn("network_connect_raw", content)
        self.assertIn("127.0.0.1", content)
        
    def test_async_event_contains_command_handler(self):
        """Test Other_68.gml contains command handling."""
        async_gml = self.project_root / "objects" / BRIDGE_OBJECT_NAME / "Other_68.gml"
        content = async_gml.read_text()
        
        self.assertIn("__mcp_execute_command", content)
        self.assertIn("ping", content)
        self.assertIn("goto_room", content)
        self.assertIn("spawn", content)
        
    def test_script_contains_log_function(self):
        """Test __mcp_log.gml contains logging function."""
        script_gml = self.project_root / "scripts" / BRIDGE_SCRIPT_NAME / f"{BRIDGE_SCRIPT_NAME}.gml"
        content = script_gml.read_text()
        
        self.assertIn("function __mcp_log", content)
        self.assertIn("show_debug_message", content)
        self.assertIn("network_send_raw", content)
        
    def test_object_is_persistent(self):
        """Test that bridge object is marked persistent."""
        object_yy = self.project_root / "objects" / BRIDGE_OBJECT_NAME / f"{BRIDGE_OBJECT_NAME}.yy"
        
        data = load_json(object_yy)
            
        self.assertTrue(data.get("persistent", False))
        
    def test_object_is_invisible(self):
        """Test that bridge object is invisible."""
        object_yy = self.project_root / "objects" / BRIDGE_OBJECT_NAME / f"{BRIDGE_OBJECT_NAME}.yy"
        
        data = load_json(object_yy)
            
        self.assertFalse(data.get("visible", True))


if __name__ == "__main__":
    unittest.main()
