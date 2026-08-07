from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from gms_helpers.gamemaker_machine_lock import GameMakerMachineLock, _consume_valid_delegation
from gms_helpers.runner import GameMakerRunner
from gms_helpers.runner_support.execution import RunnerExecutionMixin
from gms_helpers.runner_support import execution as execution_module
from gms_helpers.runner_support.igor import RunnerIgorMixin


class TestGameMakerMachineLock(unittest.TestCase):
    def test_cross_process_lock_waits_and_recovers_after_holder_exits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock_path = root / "runtime.lock"
            ready_path = root / "ready"
            release_path = root / "release"
            child_code = "\n".join(
                [
                    "import time, sys",
                    "from pathlib import Path",
                    "from gms_helpers.gamemaker_machine_lock import GameMakerMachineLock",
                    "ready, release, project = map(Path, sys.argv[1:])",
                    "with GameMakerMachineLock('child', project, timeout_seconds=5):",
                    "    ready.write_text('ready', encoding='utf-8')",
                    "    deadline = time.monotonic() + 5",
                    "    while not release.exists() and time.monotonic() < deadline:",
                    "        time.sleep(0.02)",
                ]
            )
            env = {**os.environ, "GMS_MCP_MACHINE_LOCK_PATH": str(lock_path)}
            child = subprocess.Popen(
                [sys.executable, "-c", child_code, str(ready_path), str(release_path), str(root / "child")],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready_path.exists(), "child never acquired the machine lock")

                acquired = threading.Event()

                def acquire_parent() -> None:
                    with patch.dict(os.environ, {"GMS_MCP_MACHINE_LOCK_PATH": str(lock_path)}):
                        with GameMakerMachineLock("parent", root / "parent", timeout_seconds=5):
                            acquired.set()

                thread = threading.Thread(target=acquire_parent)
                thread.start()
                self.assertFalse(acquired.wait(timeout=0.2), "parent bypassed the child process lock")
                release_path.write_text("release", encoding="utf-8")
                self.assertTrue(acquired.wait(timeout=5), "parent did not acquire after child released")
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            finally:
                release_path.write_text("release", encoding="utf-8")
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, msg=stdout + stderr)

    def test_compile_calls_from_different_projects_are_thread_serialized(self):
        active = 0
        maximum_active = 0
        guard = threading.Lock()

        def fake_compile(_runner: object, _platform: str | None = None, _runtime: str = "VM") -> bool:
            nonlocal active, maximum_active
            with guard:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.1)
            with guard:
                active -= 1
            return True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock_path = root / "runtime.lock"
            runners = [GameMakerRunner(root / "one"), GameMakerRunner(root / "two")]
            results: list[bool] = []
            with (
                patch.dict(os.environ, {"GMS_MCP_MACHINE_LOCK_PATH": str(lock_path)}),
                patch.object(RunnerIgorMixin, "compile_project", fake_compile),
            ):
                threads = [
                    threading.Thread(target=lambda runner=runner: results.append(runner.compile_project()))
                    for runner in runners
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

        self.assertEqual(results, [True, True])
        self.assertEqual(maximum_active, 1)

    def test_parent_lock_can_delegate_exactly_one_matching_compile_to_its_child(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            lock_path = root / "runtime.lock"
            child_code = "\n".join(
                [
                    "from pathlib import Path",
                    "import sys",
                    "from gms_helpers.gamemaker_machine_lock import gamemaker_machine_operation",
                    "with gamemaker_machine_operation('compile', Path(sys.argv[1])):",
                    "    print('delegated')",
                ]
            )
            with patch.dict(os.environ, {"GMS_MCP_MACHINE_LOCK_PATH": str(lock_path)}):
                with GameMakerMachineLock("compile-verify", root, timeout_seconds=5) as parent_lock:
                    env = {**os.environ, **parent_lock.delegation_environment("compile")}
                    child = subprocess.run(
                        [sys.executable, "-c", child_code, str(root)],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )

            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertEqual(child.stdout.strip(), "delegated")

    def test_delegation_metadata_is_separate_validated_and_single_use(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            lock_path = root / "runtime.lock"
            delegation_path = root / "runtime.lock.delegation"
            with patch.dict(os.environ, {"GMS_MCP_MACHINE_LOCK_PATH": str(lock_path)}):
                with GameMakerMachineLock("compile-verify", root, timeout_seconds=5) as parent_lock:
                    child_env = parent_lock.delegation_environment("compile")
                    self.assertTrue(delegation_path.is_file())

                    with patch.dict(os.environ, child_env):
                        self.assertFalse(_consume_valid_delegation("run", root))
                    self.assertTrue(delegation_path.is_file())

                    # Entry-point shims can make the eventual consumer a
                    # grandchild. The unguessable, project-bound, single-use
                    # token is the authority rather than process ancestry.
                    with (
                        patch.dict(os.environ, child_env),
                        patch("gms_helpers.gamemaker_machine_lock.os.getppid", return_value=-1),
                    ):
                        self.assertTrue(_consume_valid_delegation("compile", root))
                    self.assertFalse(delegation_path.exists())

                    with patch.dict(os.environ, child_env):
                        self.assertFalse(_consume_valid_delegation("compile", root))

    def test_public_compile_and_stop_operations_use_the_machine_lock(self):
        operations: list[str] = []

        @contextmanager
        def record_lock(operation: str, _project_root: Path):
            operations.append(operation)
            yield

        with tempfile.TemporaryDirectory() as temp_dir:
            runner = GameMakerRunner(Path(temp_dir))
            with (
                patch("gms_helpers.runner.gamemaker_machine_operation", record_lock),
                patch.object(RunnerIgorMixin, "compile_project", return_value=True),
                patch.object(RunnerExecutionMixin, "run_project_direct", return_value={"ok": True}),
                patch.object(RunnerExecutionMixin, "stop_game", return_value={"ok": True}),
            ):
                self.assertTrue(runner.compile_project())
                self.assertEqual(runner.stop_game(), {"ok": True})

        self.assertEqual(operations, ["compile", "run-stop"])

    def test_foreground_run_releases_start_lock_before_waiting_for_game_exit(self):
        active = False

        class RecordingLock:
            def __init__(self, _operation: str, _project_root: Path):
                pass

            def acquire(self) -> None:
                nonlocal active
                self.assert_not_active()
                active = True

            def release(self) -> None:
                nonlocal active
                active = False

            @staticmethod
            def assert_not_active() -> None:
                if active:
                    raise AssertionError("machine lock was already active")

        process = MagicMock()
        process.pid = 1234
        process.returncode = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_file = root / "game.yyp"
            project_file.write_text("{}", encoding="utf-8")
            runner = GameMakerRunner(root)
            with (
                patch.object(execution_module, "GameMakerMachineLock", RecordingLock),
                patch.object(runner, "_build_platform_action_command", return_value=["igor"]),
                patch.object(runner, "_wait_for_igor_idle"),
                patch.object(runner, "find_project_file", return_value=project_file),
                patch.object(runner, "_run_igor_command", return_value=process),
                patch.object(runner._session_manager, "create_session"),
                patch.object(runner._session_manager, "clear_session"),
                patch.object(
                    runner,
                    "_stream_igor_output",
                    side_effect=lambda *_args, **_kwargs: [] if not active else self.fail("lock held during wait"),
                ),
            ):
                self.assertTrue(runner._run_project_classic_approach("Windows", "VM", background=False))

        self.assertFalse(active)

    def test_exception_releases_lock_for_next_operation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.dict(os.environ, {"GMS_MCP_MACHINE_LOCK_PATH": str(root / "runtime.lock")}):
                with self.assertRaisesRegex(RuntimeError, "fault"):
                    with GameMakerMachineLock("fault", root, timeout_seconds=1):
                        raise RuntimeError("fault")
                with GameMakerMachineLock("recovery", root, timeout_seconds=1):
                    pass


if __name__ == "__main__":
    unittest.main()
