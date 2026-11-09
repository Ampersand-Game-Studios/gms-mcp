import sys
from pathlib import Path
import os
import pytest

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


@pytest.fixture(autouse=True)
def private_run_session_state(tmp_path_factory, monkeypatch):
    """Keep host session and lock state outside tmp_path, which many tests use as the project root."""
    from gms_helpers.run_session import RunSessionManager

    host_state = tmp_path_factory.mktemp("host-state")
    monkeypatch.setattr(RunSessionManager, "_state_root", staticmethod(lambda: host_state / "host-sessions"))
    monkeypatch.setenv("GMS_MCP_LOCK_DIR", str(host_state / "host-locks"))


@pytest.fixture(autouse=True)
def private_installer_state(tmp_path_factory, monkeypatch):
    """Keep installer config locks and backups out of the real ~/.gms-mcp."""
    from gms_mcp.install_support import common

    state_root = tmp_path_factory.mktemp("installer-state")
    monkeypatch.setattr(common, "_installer_state_root", lambda: state_root)
    return state_root
