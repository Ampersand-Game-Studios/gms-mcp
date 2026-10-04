"""Execute every required verification suite, independent of the caller's CWD."""

from pathlib import Path
import subprocess
import sys
import tempfile
from xml.etree import ElementTree

import pytest


TEST_ROOT = Path(__file__).resolve().parent
REQUIRED_SUITES = (
    "test_master_cli.py",
    "test_asset_helper.py",
    "test_event_helper.py",
    "test_event_validation.py",
    "test_agent_setup.py",
    "test_workflow.py",
    "test_assets_comprehensive.py",
    "test_auto_maintenance_comprehensive.py",
    "test_utils_comprehensive.py",
    "test_command_modules_comprehensive.py",
    "test_room_instance_helper.py",
    "test_room_layer_helper.py",
    "test_room_operations.py",
)


def verify_suite(suite: Path) -> None:
    assert suite.is_file(), f"Required verification suite is missing: {suite.name}"
    with tempfile.TemporaryDirectory(prefix="gms-verification-") as directory:
        report = Path(directory) / "results.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(suite), "-q", f"--junitxml={report}"],
            cwd=TEST_ROOT.parents[2],
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"{suite.name} failed:\n{result.stdout}\n{result.stderr}"
        assert report.is_file(), f"{suite.name} produced no execution evidence"
        root = ElementTree.parse(report).getroot()
        cases = list(root.iter("testcase"))
        assert cases, f"{suite.name} collected no tests"
        assert any(case.find("skipped") is None for case in cases), f"{suite.name} skipped every test"
        assert not any(case.find("failure") is not None or case.find("error") is not None for case in cases)


@pytest.mark.parametrize("suite_name", REQUIRED_SUITES)
def test_required_suite(suite_name):
    verify_suite(TEST_ROOT / suite_name)
