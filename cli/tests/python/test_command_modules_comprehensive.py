#!/usr/bin/env python3
"""
Comprehensive test suite for all command modules.
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path
import tempfile
import json

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add src directory to path
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Import all command modules
from gms_helpers.commands.asset_commands import handle_asset_create, handle_asset_delete
from gms_helpers.commands.event_commands import (
    handle_event_add, handle_event_remove, handle_event_duplicate,
    handle_event_list, handle_event_validate, handle_event_fix
)
from gms_helpers.commands.workflow_commands import (
    handle_workflow_duplicate, handle_workflow_rename,
    handle_workflow_delete, handle_workflow_swap_sprite
)
from gms_helpers.commands.room_commands import (
    handle_room_layer_add, handle_room_layer_remove, handle_room_layer_list,
    handle_room_duplicate, handle_room_rename, handle_room_delete, handle_room_list,
    handle_room_instance_add, handle_room_instance_remove, handle_room_instance_list
)
from gms_helpers.commands.maintenance_commands import (
    handle_maintenance_auto, handle_maintenance_lint, handle_maintenance_validate_json,
    handle_maintenance_list_orphans, handle_maintenance_prune_missing,
    handle_maintenance_validate_paths, handle_maintenance_dedupe_resources,
    handle_maintenance_sync_events, handle_maintenance_clean_old_files,
    handle_maintenance_clean_orphans, handle_maintenance_fix_issues
)

class TestAssetCommands(unittest.TestCase):
    """Test asset command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.asset_commands.create_script')
    def test_handle_asset_create_script(self, mock_create):
        """Test creating a script asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'script'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)

class TestEventCommands(unittest.TestCase):
    """Test event command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.event_commands.add_event')
    def test_handle_event_add(self, mock_add):
        """Test adding an event."""
        mock_add.return_value = True
        self.test_args.object = 'o_player'
        self.test_args.event = 'create'
        self.test_args.template = None
        
        result = handle_event_add(self.test_args)
        
        self.assertTrue(result)
        mock_add.assert_called_once_with('o_player', 'create', '')

class TestWorkflowCommands(unittest.TestCase):
    """Test workflow command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.workflow_commands.duplicate_asset')
    def test_handle_workflow_duplicate(self, mock_dup):
        """Test duplicating an asset."""
        mock_dup.return_value = MagicMock(success=True)
        self.test_args.project_root = '.'
        self.test_args.asset_path = 'scripts/scr_test/scr_test.yy'
        self.test_args.new_name = 'scr_new'
        
        result = handle_workflow_duplicate(self.test_args)
        
        self.assertTrue(result.success)

class TestRoomCommands(unittest.TestCase):
    """Test room command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.room_commands.add_layer')
    def test_handle_room_layer_add(self, mock_add):
        """Test adding a room layer."""
        mock_add.return_value = True
        self.test_args.room_name = 'r_test'
        self.test_args.layer_name = 'Instances_New'
        self.test_args.layer_type = 'instance'
        self.test_args.depth = 100
        
        result = handle_room_layer_add(self.test_args)
        
        self.assertTrue(result)
        mock_add.assert_called_once_with('r_test', 'Instances_New', 'instance', 100)

if __name__ == "__main__":
    unittest.main()
