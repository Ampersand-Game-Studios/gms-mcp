import sys
from pathlib import Path
import os

CLI_ROOT = Path(__file__).resolve().parents[2]      # .../cli
REPO_ROOT = Path(__file__).resolve().parents[3]     # repo root (contains gamemaker/)
GMS_HELPERS_DIR = CLI_ROOT / "gms_helpers"

# Ensure CLI modules are importable in tests:
# - `import gms_helpers.*` (package)
# - legacy tests: `import assets`, `import auto_maintenance` (module files)
sys.path.insert(0, str(CLI_ROOT))
sys.path.insert(0, str(GMS_HELPERS_DIR))

# Default GameMaker project root (directory containing the .yyp)
os.environ.setdefault("PROJECT_ROOT", str(REPO_ROOT / "gamemaker"))