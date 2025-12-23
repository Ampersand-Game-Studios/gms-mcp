"""Commands package for GMS Master CLI."""
from pathlib import Path
import sys

# Ensure src is on path so gms_helpers is importable when tests are run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))
