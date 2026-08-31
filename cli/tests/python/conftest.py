import sys
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"

# Ensure gms_helpers package is importable in tests.
sys.path.insert(0, str(SRC_ROOT))

# Use one tracked project fixture so strict Git-workspace discovery remains
# deterministic and test collection never depends on ignored local artifacts.
GAMEMAKER_DIR = REPO_ROOT / "cli" / "tests" / "fixtures" / "mcp-conformance"

os.environ.setdefault("PROJECT_ROOT", str(GAMEMAKER_DIR))
os.environ.setdefault("GM_PROJECT_ROOT", str(GAMEMAKER_DIR))
os.environ.setdefault("GMS_MCP_POST_MUTATION_VERIFY", "off")
