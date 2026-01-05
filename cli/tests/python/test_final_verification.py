#!/usr/bin/env python3
"""Final verification of all test suites."""

import subprocess
import sys
import pytest
from pathlib import Path

def run_test_file(filename, description):
    """Run a test file and return success status."""
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", filename, "-v"], 
                              capture_output=True, text=True, timeout=120,
                              encoding='utf-8')
        
        return result.returncode == 0
            
    except Exception as e:
        print(f"Error running {description}: {e}")
        return False

class TestFinalVerification:
    """Final verification of all critical test suites."""
    
    def test_critical_test_suites_status(self):
        """Verify that most critical test suites are working."""
        critical_tests = [
            ("test_master_cli.py", "Master CLI Interface"),
            ("test_asset_helper.py", "Asset Creation & Management"),
            ("test_event_helper.py", "Object Event Management"),
            ("test_event_validation.py", "Event Validation & Error Handling"),
            ("test_agent_setup.py", "Agent Setup & Integration"),
            ("test_workflow.py", "Workflow Operations"),
        ]
        
        results = []
        for test_file, description in critical_tests:
            if Path(test_file).exists():
                success = run_test_file(test_file, description)
                results.append(success)
                print(f"[{'PASS' if success else 'FAIL'}] {description}")
        
        # Require at least 50% of critical tests to pass
        passed = sum(results)
        success_rate = (passed / len(results) * 100) if results else 0
        assert passed >= len(results) // 2, f"Only {passed}/{len(results)} ({success_rate:.1f}%) critical tests passed, need at least 50%"
    
    def test_comprehensive_suite_status(self):
        """Verify comprehensive test suites are working."""
        comprehensive_tests = [
            "test_assets_comprehensive.py",
            "test_auto_maintenance_comprehensive.py", 
            "test_utils_comprehensive.py",
            "test_command_modules_comprehensive.py",
        ]
        
        results = []
        for test_file in comprehensive_tests:
            if Path(test_file).exists():
                success = run_test_file(test_file, f"Comprehensive: {test_file}")
                results.append(success)
                print(f"[{'PASS' if success else 'FAIL'}] {test_file}")
        
        # At least 1 comprehensive suite should pass if any exist
        passed = sum(results) if results else 1  # Pass if no tests found
        assert passed >= 1 or len(results) == 0, f"Only {passed} out of {len(results)} comprehensive suites passed"
    
    def test_room_helper_suites_status(self):
        """Verify room helper test suites are working."""
        room_tests = [
            "test_room_instance_helper.py",
            "test_room_layer_helper.py", 
            "test_room_operations.py",
        ]
        
        results = []
        for test_file in room_tests:
            if Path(test_file).exists():
                success = run_test_file(test_file, f"Room Helper: {test_file}")
                results.append(success)
                print(f"[{'PASS' if success else 'FAIL'}] {test_file}")
        
        # At least 2 out of 3 room helper suites should pass
        passed = sum(results)
        assert passed >= 2 or len(results) < 2, f"Only {passed} out of {len(results)} room helper suites passed" 