"""Commands package for GMS Master CLI."""
from pathlib import Path
# Ensure project root is on path so `tooling` package is importable when tests are run directly
PROJECT_ROOT = Path(__file__).resolve().parents[3]
import sys; sys.path.insert(0, str(PROJECT_ROOT)) 