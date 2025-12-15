#!/usr/bin/env python3
"""
Utils module proxy for tests
"""
import importlib
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# Import the actual utils module
try:
    from gms_helpers.utils import *
    from gms_helpers.assets import *
    from gms_helpers.auto_maintenance import *
except ImportError as e:
    print(f"Warning: Could not import from tooling.gms_helpers: {e}")
    # Fallback - try to import the module and expose its contents
    try:
        utils_module = importlib.import_module("gms_helpers.utils")
        assets_module = importlib.import_module("gms_helpers.assets")
        auto_maintenance_module = importlib.import_module("gms_helpers.auto_maintenance")
        
        # Expose all functions from utils
        globals().update({name: getattr(utils_module, name) for name in dir(utils_module) if not name.startswith('_')})
        # Expose all classes from assets
        globals().update({name: getattr(assets_module, name) for name in dir(assets_module) if not name.startswith('_')})
        # Expose all functions from auto_maintenance
        globals().update({name: getattr(auto_maintenance_module, name) for name in dir(auto_maintenance_module) if not name.startswith('_')})
    except ImportError as fallback_error:
        print(f"Fallback import also failed: {fallback_error}")
        raise 