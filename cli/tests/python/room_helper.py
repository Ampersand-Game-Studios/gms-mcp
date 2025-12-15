import importlib
import sys
from pathlib import Path

# Compatibility shim for older tests that import "room_helper" directly.
# The actual implementation lives in cli/gms_helpers/room_helper.py as "gms_helpers.room_helper".
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "cli"))
sys.path.insert(0, str(PROJECT_ROOT / "cli" / "gms_helpers"))

module = importlib.import_module("gms_helpers.room_helper")
sys.modules[__name__] = module

def __getattr__(name):
    return getattr(module, name)

if __name__ == "__main__":
    if hasattr(module, "main"):
        module.main() 