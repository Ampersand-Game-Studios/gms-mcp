import importlib
import sys
from pathlib import Path

# Compatibility shim for older tests that execute "tests/python/asset_helper.py".
# The actual implementation lives in cli/gms_helpers/asset_helper.py as "gms_helpers.asset_helper".
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "cli"))
sys.path.insert(0, str(PROJECT_ROOT / "cli" / "gms_helpers"))

module = importlib.import_module("gms_helpers.asset_helper")
sys.modules[__name__] = module

def __getattr__(name):
    return getattr(module, name)

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in ("maint", "maintenance") and sys.argv[2] == "fix-commas":
        # Map to validate-json with --fix (closest replacement)
        new_args = sys.argv[:]
        new_args[2] = "validate-json"
        sys.argv = new_args
    if hasattr(module, "main"):
        module.main() 