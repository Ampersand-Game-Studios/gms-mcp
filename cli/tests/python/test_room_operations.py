#!/usr/bin/env python3
"""
Test suite for basic room operations (duplicate, rename, delete, list).
"""

import unittest
import tempfile
import shutil
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to the path for imports
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from gms_helpers.room_helper import (
    duplicate_room, rename_room, delete_room, list_rooms,
    main
)
from gms_helpers.exceptions import GMSError, AssetNotFoundError

class TestRoomOperations(unittest.TestCase):
    """Test suite for room operations."""

    def setUp(self):
        """Set up temporary directory for testing."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        
        # Create minimal project
        (self.temp_dir / "rooms").mkdir()
        (self.temp_dir / "test.yyp").write_text("{}")

    def tearDown(self):
        """Clean up temporary directory."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)

    @patch('gms_helpers.room_helper.duplicate_asset')
    def test_duplicate_room(self, mock_dup):
        """Test duplicating a room."""
        mock_dup.return_value = MagicMock(success=True)
        
        # Create a fake room
        (self.temp_dir / "rooms" / "r_test").mkdir()
        (self.temp_dir / "rooms" / "r_test" / "r_test.yy").write_text("{}")
        
        result = duplicate_room("r_test", "r_new")
        self.assertTrue(result)
        mock_dup.assert_called_once()

    @patch('gms_helpers.room_helper.rename_asset')
    def test_rename_room(self, mock_ren):
        """Test renaming a room."""
        mock_ren.return_value = MagicMock(success=True)
        
        # Create a fake room
        (self.temp_dir / "rooms" / "r_old").mkdir()
        (self.temp_dir / "rooms" / "r_old" / "r_old.yy").write_text("{}")
        
        result = rename_room("r_old", "r_new")
        self.assertTrue(result)
        mock_ren.assert_called_once()

    @patch('gms_helpers.room_helper.delete_asset')
    def test_delete_room(self, mock_del):
        """Test deleting a room."""
        mock_del.return_value = MagicMock(success=True)
        
        # Create a fake room
        (self.temp_dir / "rooms" / "r_delete").mkdir()
        (self.temp_dir / "rooms" / "r_delete" / "r_delete.yy").write_text("{}")
        
        result = delete_room("r_delete")
        self.assertTrue(result)
        mock_del.assert_called_once()

    def test_list_rooms(self):
        """Test listing rooms."""
        # Create fake rooms
        (self.temp_dir / "rooms" / "r_1").mkdir()
        (self.temp_dir / "rooms" / "r_1" / "r_1.yy").write_text(json.dumps({
            "roomSettings": {"Width": 800, "Height": 600},
            "layers": []
        }))
        
        rooms = list_rooms()
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0]["name"], "r_1")

if __name__ == "__main__":
    unittest.main()
