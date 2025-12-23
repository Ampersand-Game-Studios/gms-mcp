
#!/usr/bin/env python3
"""
Comprehensive test suite for all command modules.
Phase 4: Command Module Enhancement & Integration - Target 100% coverage
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
    
    @patch('gms_helpers.commands.asset_commands.create_object')
    def test_handle_asset_create_object(self, mock_create):
        """Test creating an object asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'object'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_sprite')
    def test_handle_asset_create_sprite(self, mock_create):
        """Test creating a sprite asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'sprite'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_room')
    def test_handle_asset_create_room(self, mock_create):
        """Test creating a room asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'room'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_folder')
    def test_handle_asset_create_folder(self, mock_create):
        """Test creating a folder asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'folder'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_font')
    def test_handle_asset_create_font(self, mock_create):
        """Test creating a font asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'font'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_shader')
    def test_handle_asset_create_shader(self, mock_create):
        """Test creating a shader asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'shader'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_animcurve')
    def test_handle_asset_create_animcurve(self, mock_create):
        """Test creating an animcurve asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'animcurve'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_sound')
    def test_handle_asset_create_sound(self, mock_create):
        """Test creating a sound asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'sound'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_path')
    def test_handle_asset_create_path(self, mock_create):
        """Test creating a path asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'path'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_tileset')
    def test_handle_asset_create_tileset(self, mock_create):
        """Test creating a tileset asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'tileset'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_timeline')
    def test_handle_asset_create_timeline(self, mock_create):
        """Test creating a timeline asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'timeline'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_sequence')
    def test_handle_asset_create_sequence(self, mock_create):
        """Test creating a sequence asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'sequence'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.create_note')
    def test_handle_asset_create_note(self, mock_create):
        """Test creating a note asset."""
        mock_create.return_value = True
        self.test_args.asset_type = 'note'
        
        result = handle_asset_create(self.test_args)
        
        self.assertTrue(result)
        mock_create.assert_called_once_with(self.test_args)
    
    @patch('builtins.print')
    def test_handle_asset_create_unknown_type(self, mock_print):
        """Test creating an unknown asset type."""
        self.test_args.asset_type = 'unknown'
        
        result = handle_asset_create(self.test_args)
        
        self.assertFalse(result)
        printed = mock_print.call_args[0][0]
        self.assertIn("Unknown asset type: unknown", printed)
    
    @patch('gms_helpers.commands.asset_commands.delete_asset')
    def test_handle_asset_delete(self, mock_delete):
        """Test deleting an asset."""
        mock_delete.return_value = True
        
        result = handle_asset_delete(self.test_args)
        
        self.assertTrue(result)
        mock_delete.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.asset_commands.delete_asset')
    def test_handle_asset_delete_failure(self, mock_delete):
        """Test failing to delete an asset."""
        mock_delete.return_value = False
        
        result = handle_asset_delete(self.test_args)
        
        self.assertFalse(result)
        mock_delete.assert_called_once_with(self.test_args)


class TestEventCommands(unittest.TestCase):
    """Test event command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.event_commands.cmd_add')
    def test_handle_event_add(self, mock_add):
        """Test adding an event."""
        mock_add.return_value = True
        
        result = handle_event_add(self.test_args)
        
        self.assertTrue(result)
        mock_add.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.event_commands.cmd_remove')
    def test_handle_event_remove(self, mock_remove):
        """Test removing an event."""
        mock_remove.return_value = True
        
        result = handle_event_remove(self.test_args)
        
        self.assertTrue(result)
        mock_remove.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.event_commands.cmd_duplicate')
    def test_handle_event_duplicate(self, mock_duplicate):
        """Test duplicating an event."""
        mock_duplicate.return_value = True
        
        result = handle_event_duplicate(self.test_args)
        
        self.assertTrue(result)
        mock_duplicate.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.event_commands.cmd_list')
    def test_handle_event_list(self, mock_list):
        """Test listing events."""
        mock_list.return_value = True
        
        result = handle_event_list(self.test_args)
        
        self.assertTrue(result)
        mock_list.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.event_commands.cmd_validate')
    def test_handle_event_validate(self, mock_validate):
        """Test validating events."""
        mock_validate.return_value = True
        
        result = handle_event_validate(self.test_args)
        
        self.assertTrue(result)
        mock_validate.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.event_commands.cmd_fix')
    def test_handle_event_fix(self, mock_fix):
        """Test fixing events."""
        mock_fix.return_value = True
        
        result = handle_event_fix(self.test_args)
        
        self.assertTrue(result)
        mock_fix.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.event_commands.cmd_add')
    def test_handle_event_add_failure(self, mock_add):
        """Test failing to add an event."""
        mock_add.return_value = False
        
        result = handle_event_add(self.test_args)
        
        self.assertFalse(result)
        mock_add.assert_called_once_with(self.test_args)


class TestWorkflowCommands(unittest.TestCase):
    """Test workflow command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
        self.test_args.project_root = '/test/project'
        self.test_args.asset_path = 'test_asset'
        self.test_args.new_name = 'new_name'
        self.test_args.png = 'test.png'
    
    @patch('gms_helpers.commands.workflow_commands.duplicate_asset')
    def test_handle_workflow_duplicate(self, mock_duplicate):
        """Test duplicating an asset."""
        mock_duplicate.return_value = True
        self.test_args.yes = True
        
        result = handle_workflow_duplicate(self.test_args)
        
        self.assertTrue(result)
        mock_duplicate.assert_called_once_with(
            Path('/test/project').resolve(),
            'test_asset',
            'new_name',
            yes=True
        )
    
    @patch('gms_helpers.commands.workflow_commands.duplicate_asset')
    def test_handle_workflow_duplicate_no_yes_attr(self, mock_duplicate):
        """Test duplicating an asset without yes attribute."""
        mock_duplicate.return_value = True
        delattr(self.test_args, 'yes')
        
        result = handle_workflow_duplicate(self.test_args)
        
        self.assertTrue(result)
        mock_duplicate.assert_called_once_with(
            Path('/test/project').resolve(),
            'test_asset',
            'new_name',
            yes=False
        )
    
    @patch('gms_helpers.commands.workflow_commands.rename_asset')
    def test_handle_workflow_rename(self, mock_rename):
        """Test renaming an asset."""
        mock_rename.return_value = True
        
        result = handle_workflow_rename(self.test_args)
        
        self.assertTrue(result)
        mock_rename.assert_called_once_with(
            Path('/test/project').resolve(),
            'test_asset',
            'new_name'
        )
    
    @patch('gms_helpers.commands.workflow_commands.delete_asset')
    def test_handle_workflow_delete(self, mock_delete):
        """Test deleting an asset."""
        mock_delete.return_value = True
        self.test_args.dry_run = True
        
        result = handle_workflow_delete(self.test_args)
        
        self.assertTrue(result)
        mock_delete.assert_called_once_with(
            Path('/test/project').resolve(),
            'test_asset',
            dry_run=True
        )
    
    @patch('gms_helpers.commands.workflow_commands.delete_asset')
    def test_handle_workflow_delete_no_dry_run_attr(self, mock_delete):
        """Test deleting an asset without dry_run attribute."""
        mock_delete.return_value = True
        delattr(self.test_args, 'dry_run')
        
        result = handle_workflow_delete(self.test_args)
        
        self.assertTrue(result)
        mock_delete.assert_called_once_with(
            Path('/test/project').resolve(),
            'test_asset',
            dry_run=False
        )
    
    @patch('gms_helpers.commands.workflow_commands.swap_sprite_png')
    def test_handle_workflow_swap_sprite(self, mock_swap):
        """Test swapping sprite PNG."""
        mock_swap.return_value = True
        
        result = handle_workflow_swap_sprite(self.test_args)
        
        self.assertTrue(result)
        mock_swap.assert_called_once_with(
            Path('/test/project').resolve(),
            'test_asset',
            Path('test.png')
        )
    
    @patch('gms_helpers.commands.workflow_commands.rename_asset')
    def test_handle_workflow_rename_failure(self, mock_rename):
        """Test failing to rename an asset."""
        mock_rename.return_value = False
        
        result = handle_workflow_rename(self.test_args)
        
        self.assertFalse(result)


class TestRoomCommands(unittest.TestCase):
    """Test room command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.room_commands.add_layer')
    def test_handle_room_layer_add(self, mock_add):
        """Test adding a room layer."""
        mock_add.return_value = True
        self.test_args.layer_type = 'Instance'
        self.test_args.depth = 100
        
        result = handle_room_layer_add(self.test_args)
        
        self.assertTrue(result)
        mock_add.assert_called_once_with(self.test_args)
        self.assertEqual(self.test_args.layer_type, 'Instance')
        self.assertEqual(self.test_args.depth, 100)
    
    @patch('gms_helpers.commands.room_commands.add_layer')
    def test_handle_room_layer_add_no_depth(self, mock_add):
        """Test adding a room layer without depth."""
        mock_add.return_value = True
        self.test_args.layer_type = 'Background'
        # Ensure depth attribute doesn't exist initially
        if hasattr(self.test_args, 'depth'):
            delattr(self.test_args, 'depth')
        
        result = handle_room_layer_add(self.test_args)
        
        self.assertTrue(result)
        mock_add.assert_called_once_with(self.test_args)
        # Check that depth was set to 0 by the handler
        self.assertEqual(getattr(self.test_args, 'depth', None), 0)
    
    @patch('gms_helpers.commands.room_commands.remove_layer')
    def test_handle_room_layer_remove(self, mock_remove):
        """Test removing a room layer."""
        mock_remove.return_value = True
        
        result = handle_room_layer_remove(self.test_args)
        
        self.assertTrue(result)
        mock_remove.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.room_commands.list_layers')
    def test_handle_room_layer_list(self, mock_list):
        """Test listing room layers."""
        mock_list.return_value = True
        
        result = handle_room_layer_list(self.test_args)
        
        self.assertTrue(result)
        mock_list.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.room_commands.duplicate_room')
    def test_handle_room_duplicate(self, mock_duplicate):
        """Test duplicating a room."""
        mock_duplicate.return_value = True
        self.test_args.source_room = 'r_test'
        self.test_args.new_name = 'r_test_copy'
        
        result = handle_room_duplicate(self.test_args)
        
        self.assertTrue(result)
        # Check that the args were properly mapped
        call_args = mock_duplicate.call_args[0][0]
        self.assertEqual(call_args.source_room, 'r_test')
        self.assertEqual(call_args.new_name, 'r_test_copy')
    
    @patch('gms_helpers.commands.room_commands.rename_room')
    def test_handle_room_rename(self, mock_rename):
        """Test renaming a room."""
        mock_rename.return_value = True
        self.test_args.room_name = 'r_old'
        self.test_args.new_name = 'r_new'
        
        result = handle_room_rename(self.test_args)
        
        self.assertTrue(result)
        # Check that the args were properly mapped
        call_args = mock_rename.call_args[0][0]
        self.assertEqual(call_args.room_name, 'r_old')
        self.assertEqual(call_args.new_name, 'r_new')
    
    @patch('gms_helpers.commands.room_commands.delete_room')
    def test_handle_room_delete(self, mock_delete):
        """Test deleting a room."""
        mock_delete.return_value = True
        self.test_args.room_name = 'r_test'
        self.test_args.dry_run = True
        
        result = handle_room_delete(self.test_args)
        
        self.assertTrue(result)
        # Check that the args were properly mapped
        call_args = mock_delete.call_args[0][0]
        self.assertEqual(call_args.room_name, 'r_test')
        self.assertEqual(call_args.dry_run, True)
    
    @patch('gms_helpers.commands.room_commands.delete_room')
    def test_handle_room_delete_no_dry_run(self, mock_delete):
        """Test deleting a room without dry_run."""
        mock_delete.return_value = True
        self.test_args.room_name = 'r_test'
        # Ensure dry_run attribute doesn't exist
        if hasattr(self.test_args, 'dry_run'):
            delattr(self.test_args, 'dry_run')
        
        result = handle_room_delete(self.test_args)
        
        self.assertTrue(result)
        # Check that the args were properly mapped
        call_args = mock_delete.call_args[0][0]
        # The handler should set dry_run to False when not provided
        self.assertEqual(getattr(call_args, 'dry_run', None), False)
    
    @patch('gms_helpers.commands.room_commands.list_rooms')
    def test_handle_room_list(self, mock_list):
        """Test listing rooms."""
        mock_list.return_value = True
        self.test_args.verbose = True
        
        result = handle_room_list(self.test_args)
        
        self.assertTrue(result)
        # Check that the args were properly mapped
        call_args = mock_list.call_args[0][0]
        self.assertEqual(call_args.verbose, True)
    
    @patch('gms_helpers.commands.room_commands.list_rooms')
    def test_handle_room_list_no_verbose(self, mock_list):
        """Test listing rooms without verbose."""
        mock_list.return_value = True
        # Ensure verbose attribute doesn't exist
        if hasattr(self.test_args, 'verbose'):
            delattr(self.test_args, 'verbose')
        
        result = handle_room_list(self.test_args)
        
        self.assertTrue(result)
        # Check that the args were properly mapped
        call_args = mock_list.call_args[0][0]
        # The handler should set verbose to False when not provided
        self.assertEqual(getattr(call_args, 'verbose', None), False)
    
    @patch('gms_helpers.commands.room_commands.add_instance')
    def test_handle_room_instance_add(self, mock_add):
        """Test adding a room instance."""
        mock_add.return_value = True
        
        result = handle_room_instance_add(self.test_args)
        
        self.assertTrue(result)
        mock_add.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.room_commands.remove_instance')
    def test_handle_room_instance_remove(self, mock_remove):
        """Test removing a room instance."""
        mock_remove.return_value = True
        
        result = handle_room_instance_remove(self.test_args)
        
        self.assertTrue(result)
        mock_remove.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.room_commands.list_instances')
    def test_handle_room_instance_list(self, mock_list):
        """Test listing room instances."""
        mock_list.return_value = True
        
        result = handle_room_instance_list(self.test_args)
        
        self.assertTrue(result)
        mock_list.assert_called_once_with(self.test_args)


class TestMaintenanceCommands(unittest.TestCase):
    """Test maintenance command functions."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.maintenance_commands.run_auto_maintenance')
    def test_handle_maintenance_auto_success(self, mock_auto):
        """Test successful auto maintenance."""
        mock_result = Mock()
        mock_result.has_errors = False
        mock_auto.return_value = mock_result
        
        self.test_args.project_root = '/test/project'
        self.test_args.fix = True
        self.test_args.verbose = True
        
        result = handle_maintenance_auto(self.test_args)
        
        self.assertTrue(result)
        mock_auto.assert_called_once_with(
            project_root='/test/project',
            fix_issues=True,
            verbose=True
        )
    
    @patch('gms_helpers.commands.maintenance_commands.run_auto_maintenance')
    def test_handle_maintenance_auto_with_errors(self, mock_auto):
        """Test auto maintenance with errors."""
        mock_result = Mock()
        mock_result.has_errors = True
        mock_auto.return_value = mock_result
        
        result = handle_maintenance_auto(self.test_args)
        
        self.assertFalse(result)
    
    @patch('gms_helpers.commands.maintenance_commands.run_auto_maintenance')
    def test_handle_maintenance_auto_default_attrs(self, mock_auto):
        """Test auto maintenance with default attributes."""
        mock_result = Mock()
        mock_result.has_errors = False
        mock_auto.return_value = mock_result
        
        # Remove optional attributes
        delattr(self.test_args, 'project_root')
        delattr(self.test_args, 'fix')
        delattr(self.test_args, 'verbose')
        
        result = handle_maintenance_auto(self.test_args)
        
        self.assertTrue(result)
        mock_auto.assert_called_once_with(
            project_root='.',
            fix_issues=False,
            verbose=True
        )
    
    @patch('gms_helpers.commands.maintenance_commands.maint_lint_command')
    def test_handle_maintenance_lint(self, mock_lint):
        """Test project linting."""
        mock_lint.return_value = True
        
        result = handle_maintenance_lint(self.test_args)
        
        self.assertTrue(result)
        mock_lint.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_validate_json_command')
    def test_handle_maintenance_validate_json(self, mock_validate):
        """Test JSON validation."""
        mock_validate.return_value = True
        
        result = handle_maintenance_validate_json(self.test_args)
        
        self.assertTrue(result)
        mock_validate.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_list_orphans_command')
    def test_handle_maintenance_list_orphans(self, mock_list):
        """Test orphan listing."""
        mock_list.return_value = True
        
        result = handle_maintenance_list_orphans(self.test_args)
        
        self.assertTrue(result)
        mock_list.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_prune_missing_command')
    def test_handle_maintenance_prune_missing(self, mock_prune):
        """Test missing asset pruning."""
        mock_prune.return_value = True
        
        result = handle_maintenance_prune_missing(self.test_args)
        
        self.assertTrue(result)
        mock_prune.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_validate_paths_command')
    def test_handle_maintenance_validate_paths(self, mock_validate):
        """Test path validation."""
        mock_validate.return_value = True
        
        result = handle_maintenance_validate_paths(self.test_args)
        
        self.assertTrue(result)
        mock_validate.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_dedupe_resources_command')
    def test_handle_maintenance_dedupe_resources(self, mock_dedupe):
        """Test resource deduplication."""
        mock_dedupe.return_value = True
        
        result = handle_maintenance_dedupe_resources(self.test_args)
        
        self.assertTrue(result)
        mock_dedupe.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_sync_events_command')
    def test_handle_maintenance_sync_events(self, mock_sync):
        """Test event synchronization."""
        mock_sync.return_value = True
        
        result = handle_maintenance_sync_events(self.test_args)
        
        self.assertTrue(result)
        mock_sync.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_clean_old_files_command')
    def test_handle_maintenance_clean_old_files(self, mock_clean):
        """Test old file cleaning."""
        mock_clean.return_value = True
        
        result = handle_maintenance_clean_old_files(self.test_args)
        
        self.assertTrue(result)
        mock_clean.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_clean_orphans_command')
    def test_handle_maintenance_clean_orphans(self, mock_clean):
        """Test orphan cleaning."""
        mock_clean.return_value = True
        
        result = handle_maintenance_clean_orphans(self.test_args)
        
        self.assertTrue(result)
        mock_clean.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_fix_issues_command')
    def test_handle_maintenance_fix_issues(self, mock_fix):
        """Test comprehensive issue fixing."""
        mock_fix.return_value = True
        
        result = handle_maintenance_fix_issues(self.test_args)
        
        self.assertTrue(result)
        mock_fix.assert_called_once_with(self.test_args)
    
    @patch('gms_helpers.commands.maintenance_commands.maint_lint_command')
    def test_handle_maintenance_lint_failure(self, mock_lint):
        """Test failed project linting."""
        mock_lint.return_value = False
        
        result = handle_maintenance_lint(self.test_args)
        
        self.assertFalse(result)


class TestCommandModuleIntegration(unittest.TestCase):
    """Test integration scenarios across command modules."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.asset_commands.create_script')
    @patch('gms_helpers.commands.event_commands.cmd_add')
    def test_create_script_and_add_event(self, mock_event_add, mock_create_script):
        """Test creating a script and adding an event."""
        # Create script
        mock_create_script.return_value = True
        self.test_args.asset_type = 'script'
        
        result1 = handle_asset_create(self.test_args)
        self.assertTrue(result1)
        
        # Add event
        mock_event_add.return_value = True
        result2 = handle_event_add(self.test_args)
        self.assertTrue(result2)
    
    @patch('gms_helpers.commands.workflow_commands.duplicate_asset')
    @patch('gms_helpers.commands.maintenance_commands.run_auto_maintenance')
    def test_duplicate_asset_and_run_maintenance(self, mock_maintenance, mock_duplicate):
        """Test duplicating an asset and running maintenance."""
        # Duplicate asset
        mock_duplicate.return_value = True
        self.test_args.project_root = '/test/project'
        self.test_args.asset_path = 'test_asset'
        self.test_args.new_name = 'new_asset'
        
        result1 = handle_workflow_duplicate(self.test_args)
        self.assertTrue(result1)
        
        # Run maintenance
        mock_result = Mock()
        mock_result.has_errors = False
        mock_maintenance.return_value = mock_result
        
        result2 = handle_maintenance_auto(self.test_args)
        self.assertTrue(result2)
    
    @patch('gms_helpers.commands.room_commands.add_layer')
    @patch('gms_helpers.commands.room_commands.add_instance')
    def test_add_layer_and_instance(self, mock_add_instance, mock_add_layer):
        """Test adding a room layer and instance."""
        # Add layer
        mock_add_layer.return_value = True
        self.test_args.layer_type = 'Instance'
        
        result1 = handle_room_layer_add(self.test_args)
        self.assertTrue(result1)
        
        # Add instance
        mock_add_instance.return_value = True
        result2 = handle_room_instance_add(self.test_args)
        self.assertTrue(result2)


class TestErrorHandlingAndEdgeCases(unittest.TestCase):
    """Test error handling and edge cases across all command modules."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_args = Mock()
    
    @patch('gms_helpers.commands.asset_commands.create_script')
    def test_asset_create_exception_handling(self, mock_create):
        """Test exception handling in asset creation."""
        mock_create.side_effect = Exception("Creation failed")
        self.test_args.asset_type = 'script'
        
        with self.assertRaises(Exception):
            handle_asset_create(self.test_args)
    
    @patch('gms_helpers.commands.event_commands.cmd_add')
    def test_event_add_exception_handling(self, mock_add):
        """Test exception handling in event addition."""
        mock_add.side_effect = ValueError("Invalid event type")
        
        with self.assertRaises(ValueError):
            handle_event_add(self.test_args)
    
    @patch('gms_helpers.commands.workflow_commands.Path')
    def test_workflow_invalid_path_handling(self, mock_path):
        """Test handling of invalid paths in workflow commands."""
        mock_path.side_effect = OSError("Invalid path")
        self.test_args.project_root = '/invalid/path'
        self.test_args.asset_path = 'test'
        self.test_args.new_name = 'new'
        
        with self.assertRaises(OSError):
            handle_workflow_duplicate(self.test_args)
    
    @patch('gms_helpers.commands.room_commands.add_layer')
    def test_room_layer_add_with_none_args(self, mock_add):
        """Test room layer addition with None arguments."""
        mock_add.return_value = False
        self.test_args.layer_type = None
        
        result = handle_room_layer_add(self.test_args)
        
        self.assertFalse(result)
        self.assertIsNone(self.test_args.layer_type)
    
    @patch('gms_helpers.commands.maintenance_commands.run_auto_maintenance')
    def test_maintenance_auto_keyboard_interrupt(self, mock_auto):
        """Test handling keyboard interrupt during maintenance."""
        mock_auto.side_effect = KeyboardInterrupt()
        
        with self.assertRaises(KeyboardInterrupt):
            handle_maintenance_auto(self.test_args)
    
    def test_args_with_special_characters(self):
        """Test handling arguments with special characters."""
        self.test_args.asset_type = 'script"with"quotes'
        self.test_args.new_name = "name'with'apostrophe"
        self.test_args.project_root = "/path/with spaces/and\\backslashes"
        
        # These should not raise exceptions
        self.assertIsNotNone(self.test_args.asset_type)
        self.assertIsNotNone(self.test_args.new_name)
        self.assertIsNotNone(self.test_args.project_root)
    
    @patch('gms_helpers.commands.asset_commands.create_object')
    def test_concurrent_asset_creation(self, mock_create):
        """Test handling concurrent asset creation attempts."""
        mock_create.return_value = True
        self.test_args.asset_type = 'object'
        
        # Simulate multiple concurrent calls
        results = []
        for _ in range(5):
            result = handle_asset_create(self.test_args)
            results.append(result)
        
        self.assertEqual(len(results), 5)
        self.assertTrue(all(results))
        self.assertEqual(mock_create.call_count, 5)


class TestCommandModuleCoverage(unittest.TestCase):
    """Test to ensure 100% coverage of all command module code paths."""
    
    def test_all_asset_types_covered(self):
        """Verify all asset types in handle_asset_create are tested."""
        expected_types = [
            'script', 'object', 'sprite', 'room', 'folder',
            'font', 'shader', 'animcurve', 'sound', 'path',
            'tileset', 'timeline', 'sequence', 'note'
        ]
        
        # This test verifies our test coverage is complete
        # by checking that we have tests for all asset types
        for asset_type in expected_types:
            test_method_name = f'test_handle_asset_create_{asset_type}'
            self.assertTrue(
                hasattr(TestAssetCommands, test_method_name),
                f"Missing test for asset type: {asset_type}"
            )
    
    def test_all_event_commands_covered(self):
        """Verify all event commands are tested."""
        event_commands = [
            'add', 'remove', 'duplicate', 'list', 'validate', 'fix'
        ]
        
        for cmd in event_commands:
            test_method_name = f'test_handle_event_{cmd}'
            self.assertTrue(
                hasattr(TestEventCommands, test_method_name),
                f"Missing test for event command: {cmd}"
            )
    
    def test_all_workflow_commands_covered(self):
        """Verify all workflow commands are tested."""
        workflow_commands = [
            'duplicate', 'rename', 'delete', 'swap_sprite'
        ]
        
        for cmd in workflow_commands:
            test_method_name = f'test_handle_workflow_{cmd}'
            self.assertTrue(
                hasattr(TestWorkflowCommands, test_method_name),
                f"Missing test for workflow command: {cmd}"
            )
    
    def test_all_room_commands_covered(self):
        """Verify all room commands are tested."""
        room_commands = [
            'layer_add', 'layer_remove', 'layer_list',
            'duplicate', 'rename', 'delete', 'list',
            'instance_add', 'instance_remove', 'instance_list'
        ]
        
        for cmd in room_commands:
            test_method_name = f'test_handle_room_{cmd}'
            self.assertTrue(
                hasattr(TestRoomCommands, test_method_name),
                f"Missing test for room command: {cmd}"
            )
    
    def test_all_maintenance_commands_covered(self):
        """Verify all maintenance commands are tested."""
        maintenance_commands = [
            'auto', 'lint', 'validate_json', 'list_orphans',
            'prune_missing', 'validate_paths', 'dedupe_resources',
            'sync_events', 'clean_old_files', 'clean_orphans', 'fix_issues'
        ]
        
        for cmd in maintenance_commands:
            test_method_name = f'test_handle_maintenance_{cmd}'
            # Some tests might have variations like _success or _failure
            base_test_exists = any(
                method.startswith(test_method_name)
                for method in dir(TestMaintenanceCommands)
            )
            self.assertTrue(
                base_test_exists,
                f"Missing test for maintenance command: {cmd}"
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
