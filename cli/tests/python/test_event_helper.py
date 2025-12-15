#!/usr/bin/env python3
"""
Unit tests for event_helper.py
Simplified version that works with unittest instead of pytest.
"""

import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, Mock
import unittest
import sys
import os

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# Import the module we're testing
from gms_helpers.event_helper import (
    _event_to_filename, _filename_to_event, _parse_event_spec,
    cmd_add, cmd_remove, cmd_list, cmd_validate, cmd_fix, cmd_duplicate
)


class TestEventHelper(unittest.TestCase):
    """Test suite for event helper functions."""
    
    def test_event_to_filename(self):
        """Test event type/num to filename conversion."""
        self.assertEqual(_event_to_filename(0, 0), "Create_0.gml")
        self.assertEqual(_event_to_filename(1, 0), "Destroy_0.gml")
        self.assertEqual(_event_to_filename(3, 2), "Step_2.gml")
        self.assertEqual(_event_to_filename(8, 64), "Draw_64.gml")
        self.assertEqual(_event_to_filename(4, 0, "o_wall"), "Collision_o_wall.gml")
    
    def test_filename_to_event(self):
        """Test filename to event type/num conversion."""
        self.assertEqual(_filename_to_event("Create_0.gml"), (0, 0, None))
        self.assertEqual(_filename_to_event("Step_2.gml"), (3, 2, None))
        self.assertEqual(_filename_to_event("Draw_64.gml"), (8, 64, None))
        self.assertEqual(_filename_to_event("Collision_o_wall.gml"), (4, 0, "o_wall"))
    
    def test_parse_event_spec(self):
        """Test parsing event specifications."""
        self.assertEqual(_parse_event_spec("create"), (0, 0, None))
        self.assertEqual(_parse_event_spec("step"), (3, 0, None))
        self.assertEqual(_parse_event_spec("step:end"), (3, 2, None))
        self.assertEqual(_parse_event_spec("step:1"), (3, 1, None))
        self.assertEqual(_parse_event_spec("draw:gui"), (8, 64, None))
        self.assertEqual(_parse_event_spec("collision:o_wall"), (4, 0, "o_wall"))
    
    @patch('gms_helpers.event_helper.add_event')
    def test_cmd_add(self, mock_add):
        """Test cmd_add function."""
        mock_add.return_value = True
        args = Mock()
        args.object = 'o_test'
        args.event = 'create'
        args.template = None
        
        result = cmd_add(args)
        
        self.assertTrue(result)
        mock_add.assert_called_once()
    
    @patch('gms_helpers.event_helper.remove_event')
    def test_cmd_remove(self, mock_remove):
        """Test cmd_remove function."""
        mock_remove.return_value = True
        args = Mock()
        args.object = 'o_test'
        args.event = 'create'
        
        result = cmd_remove(args)
        
        self.assertTrue(result)
        mock_remove.assert_called_once()
    
    @patch('gms_helpers.event_helper.list_events')
    def test_cmd_list(self, mock_list):
        """Test cmd_list function."""
        mock_list.return_value = []
        args = Mock()
        args.object = 'o_test'
        args.verbose = False
        
        result = cmd_list(args)
        
        self.assertTrue(result)
        mock_list.assert_called_once_with('o_test')
    
    @patch('gms_helpers.event_helper.validate_events')
    def test_cmd_validate(self, mock_validate):
        """Test cmd_validate function."""
        mock_report = Mock()
        mock_report.errors = []
        mock_report.warnings = []
        mock_report.missing_files = []
        mock_report.orphan_files = []
        mock_report.duplicates = []
        mock_validate.return_value = mock_report
        
        args = Mock()
        args.object = 'o_test'
        
        result = cmd_validate(args)
        
        self.assertTrue(result)
        mock_validate.assert_called_once_with('o_test')
    
    @patch('gms_helpers.event_helper.fix_events')
    def test_cmd_fix(self, mock_fix):
        """Test cmd_fix function."""
        mock_report = Mock()
        mock_report.files_created = 0
        mock_report.files_deleted = 0  # Added missing attribute
        mock_report.events_added = 0
        mock_report.events_removed = 0
        mock_report.issues_fixed = []  # Added missing attribute
        mock_fix.return_value = mock_report
        
        args = Mock()
        args.object = 'o_test'
        args.safe_mode = True  # Fixed: should be safe_mode not safe
        args.dry_run = False
        
        result = cmd_fix(args)
        
        self.assertTrue(result)
        mock_fix.assert_called_once()
    
    @patch('gms_helpers.event_helper.duplicate_event')
    def test_cmd_duplicate(self, mock_duplicate):
        """Test cmd_duplicate function."""
        mock_duplicate.return_value = True
        args = Mock()
        args.object = 'o_test'
        args.source_event = 'create'  # Fixed: should be source_event not source
        args.target_num = 1
        
        result = cmd_duplicate(args)
        
        self.assertTrue(result)
        mock_duplicate.assert_called_once()
    
    def test_cmd_functions_with_failures(self):
        """Test command functions handling failures."""
        # Test cmd_add with invalid event
        args = Mock()
        args.object = 'o_test'
        args.event = 'invalid_event'
        args.template = None
        
        with patch('gms_helpers.event_helper._parse_event_spec') as mock_parse:
            mock_parse.side_effect = ValueError("Invalid event")
            result = cmd_add(args)
            self.assertFalse(result)
        
        # Test cmd_validate with object not found
        args = Mock()
        args.object = 'o_nonexistent'
        
        with patch('gms_helpers.event_helper.validate_events') as mock_validate:
            mock_validate.return_value = None
            result = cmd_validate(args)
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)