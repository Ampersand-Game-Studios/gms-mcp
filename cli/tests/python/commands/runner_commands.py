
# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

"""Stub runner command implementations for test environment.
These no-op handlers satisfy import requirements in tooling.gms_helpers.gms
so that the CLI help system and parser building work during unit tests.
They always return True.
"""

def handle_runner_compile(args=None):  # noqa: D401
    """Pretend to compile project (always succeeds)."""
    print("✅ compile (stub)")
    return True

def handle_runner_run(args=None):
    """Pretend to start project (always succeeds)."""
    print("✅ run (stub)")
    return True

def handle_runner_stop(args=None):
    """Pretend to stop project (always succeeds)."""
    print("✅ stop (stub)")
    return True

def handle_runner_status(args=None):
    """Pretend project is not running (always succeeds)."""
    print("status: not running (stub)")
    return True 