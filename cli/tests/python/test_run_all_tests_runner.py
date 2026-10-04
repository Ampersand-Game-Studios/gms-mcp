"""The full-suite entry point must collect tests and propagate every failure."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


RUNNER_PATH = Path(__file__).with_name("run_all_tests.py")
spec = importlib.util.spec_from_file_location("run_all_tests_module", RUNNER_PATH)
run_all_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_all_tests)


@pytest.mark.parametrize("exit_code", [0, 1, 2, 5])
def test_propagates_pytest_result(exit_code):
    with (
        patch.object(run_all_tests, "find_spec", return_value=object()),
        patch.object(run_all_tests.subprocess, "run") as run,
    ):
        run.return_value.returncode = exit_code
        assert run_all_tests.main() == exit_code
    args = run.call_args.args[0]
    assert args[1:3] == ["-m", "pytest"]
    assert Path(args[3]).is_absolute()
    assert run.call_args.kwargs["env"]["GMS_TEST_SUITE"] == "1"


def test_missing_dependencies_fail_without_skipping():
    with (
        patch.object(run_all_tests, "find_spec", return_value=None),
        patch.object(run_all_tests.subprocess, "run") as run,
    ):
        assert run_all_tests.main() == 1
    run.assert_not_called()
