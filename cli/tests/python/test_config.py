#!/usr/bin/env python3
"""
Test configuration and common imports
"""
import sys
from pathlib import Path

# Define PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Add necessary paths
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

# Export PROJECT_ROOT for other tests
__all__ = ['PROJECT_ROOT']
