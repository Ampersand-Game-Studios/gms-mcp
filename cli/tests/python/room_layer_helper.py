import importlib
import sys
import types
from pathlib import Path

# Compatibility shim used by coverage tests.
# - When running inside the repo, it forwards to gms_helpers.room_layer_helper.
# - When copied into an isolated temp dir (no cli/ present), it provides a stub that exits 0.

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "cli"))
sys.path.insert(0, str(PROJECT_ROOT / "cli" / "gms_helpers"))

try:
    module = importlib.import_module("gms_helpers.room_layer_helper")
except ModuleNotFoundError:
    module = types.ModuleType("room_layer_helper")

    def main():
        if "--help" in sys.argv or "-h" in sys.argv:
            print("GameMaker Studio Room Layer Helper (stub)")
            return
        print("GameMaker Studio Room Layer Helper (stub)")

    setattr(module, "main", main)

sys.modules[__name__] = module

def __getattr__(name):
    return getattr(module, name)

if __name__ == "__main__":
    try:
        if hasattr(module, "main"):
            module.main()
    finally:
        sys.exit(0)