from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts import build_release, generate_quality_reports as quality
from scripts.verify_release_certification import verify_reports
from test_release_certification import _report


@pytest.mark.parametrize(
    "contents,expected",
    [
        ('<testsuite tests="100"/>', False),
        ("<testsuite><testcase><skipped/></testcase></testsuite>", False),
        ("<testsuite><testcase><failure/></testcase></testsuite>", False),
        ("<testsuite><testcase><error/></testcase></testsuite>", False),
        ("<testsuite><testcase/></testsuite>", True),
    ],
)
def test_quality_requires_real_passing_testcase_evidence(tmp_path, contents, expected):
    report = tmp_path / "junit.xml"
    report.write_text(contents)
    assert quality.has_executed_junit_cases(report) is expected


@pytest.mark.parametrize("branches,coverage,expected", [(0, 100, False), (10, 74.99, False), (10, 75, True)])
def test_branch_gate_requires_measurement_and_threshold(branches, coverage, expected):
    gate = quality.evaluate_coverage_gates(
        {"overall": 100, "modules": [], "branches_valid": branches, "branch_coverage": coverage},
        min_overall=85,
        min_module=50,
        min_branch=75,
        exclude_modules=[],
    )
    assert gate["ok"] is expected
    assert gate["min_branch"] == 75


@pytest.mark.parametrize("setting", ["min_overall", "min_module", "min_branch"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), -1, 101])
def test_coverage_gate_rejects_invalid_thresholds(setting, invalid):
    thresholds = {"min_overall": 85, "min_module": 50, "min_branch": 75}
    thresholds[setting] = invalid
    with pytest.raises(ValueError, match="finite percentage"):
        quality.evaluate_coverage_gates(
            {"overall": 100, "modules": [], "branches_valid": 10, "branch_coverage": 100},
            exclude_modules=[],
            **thresholds,
        )


@pytest.mark.parametrize("field", ["overall", "branch_coverage", "module"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), -1, 101])
def test_coverage_gate_rejects_invalid_measurements(field, invalid):
    coverage = {
        "overall": 100,
        "modules": [{"module": "critical", "coverage": 100}],
        "branches_valid": 10,
        "branch_coverage": 100,
    }
    if field == "module":
        coverage["modules"][0]["coverage"] = invalid
    else:
        coverage[field] = invalid
    with pytest.raises(ValueError, match="finite percentage"):
        quality.evaluate_coverage_gates(coverage, min_overall=85, min_module=50, min_branch=75, exclude_modules=[])


@pytest.mark.parametrize("invalid", ["nan", "inf", "-inf", "-1", "101", "invalid"])
def test_environment_coverage_thresholds_fail_closed(monkeypatch, invalid):
    monkeypatch.setenv("GMS_MCP_MIN_OVERALL_COVERAGE", invalid)
    with pytest.raises(ValueError, match="finite percentage"):
        quality._float_setting("GMS_MCP_MIN_OVERALL_COVERAGE", 85)


@pytest.mark.parametrize("argument", ["--min-overall-coverage", "--min-module-coverage", "--min-branch-coverage"])
def test_cli_coverage_thresholds_reject_nan(monkeypatch, argument):
    monkeypatch.setattr("sys.argv", ["quality", argument, "nan"])
    with pytest.raises(SystemExit) as failure:
        quality.parse_args()
    assert failure.value.code == 2


@pytest.mark.parametrize(
    "revision,dirty,expected",
    [("a" * 40, False, True), ("b" * 40, False, False), ("a" * 40, True, False), (None, None, False)],
)
def test_release_certification_binds_clean_exact_revision(tmp_path, revision, dirty, expected):
    report = _report("gm-2024")
    report["fixture"].update(source_revision=revision, source_dirty=dirty)
    (tmp_path / "real_gamemaker_smoke-macos-gm-2024.json").write_text(json.dumps(report))
    assert (not verify_reports(tmp_path, ["macos-gm-2024"], expected_revision="a" * 40)) is expected


@pytest.mark.parametrize(
    "check",
    [
        "resolve_cancel_left_existing_asset",
        "resolve_alternative_name_compiled",
        "resolve_texture_reassignment_compiled",
        "resolve_dependency_delete_cancelled",
    ],
)
@pytest.mark.parametrize("value", [None, False])
def test_release_certification_requires_every_resolve_check(tmp_path, check, value):
    report = _report("gm-2024")
    if value is None:
        report["checks"].pop(check)
    else:
        report["checks"][check] = value
    (tmp_path / "real_gamemaker_smoke-macos-gm-2024.json").write_text(json.dumps(report))
    assert any(check in error for error in verify_reports(tmp_path, ["macos-gm-2024"]))


def test_sdist_normalization_makes_metadata_and_order_reproducible(tmp_path):
    paths = [tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"]
    for index, path in enumerate(paths):
        with tarfile.open(path, "w:gz") as archive:
            names = ["source/a.txt", "source/b.txt"]
            if index:
                names.reverse()
            for name in names:
                member = tarfile.TarInfo(name)
                member.size = 4
                member.mtime = 123 + index
                member.uid = 10 + index
                member.uname = "private-user"
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(b"data"))
        build_release.normalize_sdist(path, 100)
    assert paths[0].read_bytes() == paths[1].read_bytes()


def test_release_build_refuses_to_overwrite_existing_artifacts(tmp_path):
    existing = tmp_path / "release"
    existing.mkdir()
    sentinel = existing / "user-artifact"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match="never overwritten"):
        build_release.build_reproducibly(existing)
    assert sentinel.read_text() == "keep"
