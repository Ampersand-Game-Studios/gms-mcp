import sys
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[3]     # repo root (contains gamemaker/)
SRC_ROOT = REPO_ROOT / "src"

# Ensure gms_helpers package is importable in tests.
sys.path.insert(0, str(SRC_ROOT))

# Default GameMaker project root (directory containing the .yyp)
os.environ.setdefault("PROJECT_ROOT", str(REPO_ROOT / "gamemaker"))
