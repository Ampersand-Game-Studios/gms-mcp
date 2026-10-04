"""Reject empty, skipped, missing, or falsely successful verification evidence."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import test_final_verification as gate


def test_missing_suite_is_an_error(tmp_path):
    with pytest.raises(AssertionError, match="missing"):
        gate.verify_suite(tmp_path / "test_missing.py")


@pytest.mark.parametrize(
    "xml,code,valid",
    [
        ("<testsuites/>", 0, False),
        ("<testsuites><testcase><skipped/></testcase></testsuites>", 0, False),
        ("<testsuites><testcase><failure/></testcase></testsuites>", 0, False),
        ("<testsuites><testcase/></testsuites>", 1, False),
        ("<testsuites><testcase/></testsuites>", 0, True),
    ],
)
def test_verification_requires_executed_passing_cases(tmp_path, xml, code, valid):
    suite = tmp_path / "test_case.py"
    suite.touch()

    def run(command, **kwargs):
        assert Path(command[3]).is_absolute()
        Path(command[-1].split("=", 1)[1]).write_text(xml)
        return SimpleNamespace(returncode=code, stdout="", stderr="")

    with patch.object(gate.subprocess, "run", side_effect=run):
        if valid:
            gate.verify_suite(suite)
        else:
            with pytest.raises(AssertionError):
                gate.verify_suite(suite)
