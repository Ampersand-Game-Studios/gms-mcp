#!/usr/bin/env python3
"""
Test configuration and common imports
"""
import sys
from pathlib import Path

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add necessary paths
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'tooling' / 'gms_helpers'))

# Pre-import modules to avoid import errors
try:
    import gms_helpers.utils as utils_module
    import gms_helpers.assets as assets_module
    import gms_helpers.auto_maintenance as auto_maintenance_module
    import gms_helpers.workflow as workflow_module
    import gms_helpers.room_instance_helper as room_instance_helper_module
    import gms_helpers.room_layer_helper as room_layer_helper_module
    import gms_helpers.event_helper as event_helper_module
    
    # Make modules available as if imported directly
    sys.modules['utils'] = utils_module
    sys.modules['assets'] = assets_module
    sys.modules['auto_maintenance'] = auto_maintenance_module
    sys.modules['workflow'] = workflow_module
    sys.modules['room_instance_helper'] = room_instance_helper_module
    sys.modules['room_layer_helper'] = room_layer_helper_module
    sys.modules['event_helper'] = event_helper_module
    
except ImportError as e:
    print(f"Warning: Failed to pre-import modules: {e}")

# Export PROJECT_ROOT for other tests
__all__ = ['PROJECT_ROOT'] 