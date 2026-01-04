import sys
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[3]     # repo root (contains gamemaker/)
SRC_ROOT = REPO_ROOT / "src"

# Ensure gms_helpers package is importable in tests.
sys.path.insert(0, str(SRC_ROOT))

# Default GameMaker project root (directory containing the .yyp)
GAMEMAKER_DIR = REPO_ROOT / "gamemaker"
if not GAMEMAKER_DIR.exists():
    GAMEMAKER_DIR.mkdir(parents=True, exist_ok=True)
    # Create minimal .yyp if missing
    if not any(GAMEMAKER_DIR.glob("*.yyp")):
        with (GAMEMAKER_DIR / "test.yyp").open("w") as f:
            f.write('{"resources":[]}')

os.environ.setdefault("PROJECT_ROOT", str(GAMEMAKER_DIR))
