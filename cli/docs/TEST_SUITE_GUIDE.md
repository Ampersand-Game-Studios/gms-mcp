# Test Suite Quick-Start Guide

## Overview

The GameMaker CLI Tools come with a comprehensive test suite that validates all functionality across 19 test files covering asset creation, maintenance operations, room management, and more.

## 🚀 Running Tests

### Basic Usage
Recommended: run the test runner from the repo root so paths are resolved consistently.

```powershell
# Run all tests from repo root
python cli/tests/python/run_all_tests.py
```

### Test Runner Features
- **Automatic Python detection**: Finds the best Python executable
- **Comprehensive reporting**: Shows pass/fail status for each test file
- **Progress tracking**: Real-time feedback as tests execute
- **Summary statistics**: Final count of passed/failed tests

### Expected Output
```
🚀 GameMaker Project Test Suite Runner
============================================================
🐍 Using Python: C:\...\python.exe
📦 Version: Python 3.13.5
============================================================
Found 19 test files:
  • test_all_phases.py
  • test_assets_comprehensive.py
  ...

📊 TEST SUMMARY
============================================================
test_command_modules_comprehensive.py ✅ PASS
test_directory_validation_fixed.py    ✅ PASS
test_event_helper.py                  ✅ PASS
...

📈 OVERALL RESULTS:
   Passed: 19/19
   Failed: 0/19
```

## 🔒 TempProject Isolation System

### What is TempProject?
The test suite uses a **critical safety feature** called `TempProject` that prevents tests from accidentally modifying your real GameMaker project.

### How It Works
```python
class TempProject:
    """Context manager to build a tiny GM project for testing."""
    def __enter__(self):
        self.original_cwd = os.getcwd()  # Save current directory
        self.dir = Path(tempfile.mkdtemp())
        # Build basic project structure
        for f in ["scripts", "objects", "sprites", "rooms", "folders"]:
            (self.dir / f).mkdir()
        # Create minimal .yyp file
        save_pretty_json(self.dir / "test.yyp", {"resources": [], "Folders": []})
        os.chdir(self.dir)  # Change to temp directory
        return self.dir

    def __exit__(self, exc_type, exc, tb):
        os.chdir(self.original_cwd)  # Restore original directory
        shutil.rmtree(self.dir)     # Clean up temp files
```

### Critical Safety Benefits
1. **Isolated Environment**: Each test creates a temporary GameMaker project
2. **Working Directory Protection**: Tests change to temp directory before operations
3. **Automatic Cleanup**: Temp projects are completely deleted after each test
4. **Real Project Safety**: Your actual project files are never touched

### The Bug That Was Fixed
**⚠️ CRITICAL INCIDENT**: Originally, TempProject was **NOT** changing the working directory, causing tests to operate on the real project files. This led to:
- Catastrophic destruction of actual project rooms
- Loss of legitimate asset files
- Tests appearing to pass while destroying real data

**The Fix**: Added `os.chdir(self.dir)` in `__enter__()` and `os.chdir(self.original_cwd)` in `__exit__()` to ensure tests always operate in isolation.

## 🎯 Selective Test Running

### Run Individual Test Files
```powershell
# Run specific test from repo root
python cli/tests/python/test_asset_helper.py

# Run with verbose output
python cli/tests/python/test_asset_helper.py -v
```

### Run Test Categories

**Core Functionality Tests**:
```powershell
python cli/tests/python/test_command_modules_comprehensive.py  # All CLI commands
python cli/tests/python/test_assets_comprehensive.py           # Asset creation
python cli/tests/python/test_utils_comprehensive.py            # Utility functions
```

**Room Management Tests**:
```powershell
python cli/tests/python/test_room_operations.py       # Room duplicate/rename/delete
python cli/tests/python/test_room_layer_helper.py     # Room layer management
python cli/tests/python/test_room_instance_helper.py  # Room instance management
```

**Maintenance Tests**:
```powershell
python cli/tests/python/test_auto_maintenance_comprehensive.py  # Full maintenance suite
```

**Integration Tests**:
```powershell
python cli/tests/python/test_all_phases.py                # End-to-end workflow
python cli/tests/python/test_directory_validation_fixed.py # Project location validation
```

### Performance Testing
```powershell
python cli/tests/python/test_auto_maintenance_comprehensive.py  # Maintenance suite (few seconds)
python cli/tests/python/test_all_phases.py                      # Full integration (10+ seconds)
```

## 🐛 Troubleshooting

### Common Issues

**1. Import Errors (`ModuleNotFoundError`)**
```
ModuleNotFoundError: No module named 'gms_helpers'
```
**Cause**: Test not run from correct directory or Python path issues
**Solution**: Use `python cli/tests/python/run_all_tests.py` or set `PYTHONPATH=src`

**2. PROJECT_ROOT Not Defined**
```
NameError: name 'PROJECT_ROOT' is not defined
```
**Cause**: Path configuration issue
**Solution**: Use the test runner or set `PYTHONPATH=src`

**3. Relative Import Errors**
```
ImportError: attempted relative import with no known parent package
```
**Cause**: Running individual test files incorrectly
**Solution**: Use the test runner: `python cli/tests/python/run_all_tests.py`

**4. Test Failures Due to Environment**
- Some tests expect specific project structure
- Directory validation tests require being in correct location
- Maintenance tests may timeout on slower systems

### Expected Test Status
As of current version:
- **Consistently Passing**: 19/19 test files with the runner
- **Core Functionality**: All critical CLI features are covered

### Test Environment Requirements
1. **Python 3.8+** (detected automatically)
2. **Run via test runner** (`python cli/tests/python/run_all_tests.py`)
3. **Project structure intact** (for validation tests)
4. **No active GameMaker IDE** (file locking issues)

## 📊 Test Coverage

### What's Tested
- ✅ **All CLI Commands**: Asset creation, maintenance, room operations
- ✅ **Error Handling**: Invalid inputs, missing files, timeout protection
- ✅ **Integration Workflows**: End-to-end scenarios
- ✅ **Safety Systems**: TempProject isolation, directory validation
- ✅ **Reference Scanning**: Comprehensive asset rename operations
- ✅ **Maintenance Operations**: Orphan cleanup, JSON validation, path checking

### Test File Overview
| Test File | Purpose | Typical Runtime |
|-----------|---------|----------------|
| `test_command_modules_comprehensive.py` | All CLI commands | < 1 second |
| `test_directory_validation_fixed.py` | Project location safety | < 1 second |
| `test_event_helper.py` | Object event management | < 1 second |
| `test_auto_maintenance_comprehensive.py` | Full maintenance suite | few seconds |
| `test_all_phases.py` | End-to-end integration | 10+ seconds |

## 🔧 Advanced Usage

### Running with Coverage (if pytest installed)
```powershell
pip install pytest pytest-cov
pytest --cov=gms_helpers --cov-report=html
```

### Environment Variables
```powershell
# Override Python executable
$env:PYTHON_EXEC_OVERRIDE = "python3.11"
python cli/tests/python/run_all_tests.py
```

### Development Testing
```powershell
# Quick smoke test (fastest tests only)
python cli/tests/python/test_event_helper.py
python cli/tests/python/test_command_modules_comprehensive.py

# Full validation (all tests)
python cli/tests/python/run_all_tests.py
```

## 🎉 Success Indicators

**All Tests Passing**:
```
🎉 ALL TESTS PASSED! 🎉
```

**Partial Success** (expected for environment-dependent tests):
```
📈 OVERALL RESULTS:
   Passed: 19/19
   Failed: 0/19
```

If you see unexpected failures, re-run via the test runner and confirm `PYTHONPATH=src`.

---

## Summary

The test suite provides comprehensive validation of all CLI functionality while ensuring your real project files are never at risk. The TempProject isolation system is a critical safety feature that creates temporary test environments for each test, preventing accidental damage to your actual GameMaker project.

**Remember**: Use the test runner (or set `PYTHONPATH=src`) and trust the TempProject isolation to keep your real project safe!
