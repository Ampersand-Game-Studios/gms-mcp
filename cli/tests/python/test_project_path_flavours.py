"""Portable regressions for Windows rooted paths at project boundaries."""

import json
from pathlib import PurePosixPath, PureWindowsPath
from unittest.mock import PropertyMock, patch

import pytest

from gms_helpers.exceptions import ValidationError
from gms_helpers.gml_index.index import GMLIndex
from gms_helpers.introspection import get_asset_yy_path
from gms_helpers.path_safety import project_relative_path
from gms_mcp.server.validation import validate_mcp_tool_arguments


class WindowsSyntaxPath(PureWindowsPath):
    """Exercise native Windows parsing without touching a Windows filesystem."""

    def resolve(self, *args, **kwargs):
        raise AssertionError("Invalid input reached filesystem resolution")


class PosixSyntaxPath(PurePosixPath):
    def resolve(self, *args, **kwargs):
        raise AssertionError("Invalid input reached filesystem resolution")


@pytest.fixture(params=[PosixSyntaxPath, WindowsSyntaxPath], ids=["posix", "windows"])
def syntax_path(request):
    return request.param


@pytest.mark.parametrize(
    "value",
    ["/scripts/scr/scr.yy", "\\scripts\\scr\\scr.yy", "D:scripts/scr/scr.yy", "D:/scripts/scr/scr.yy"],
)
def test_project_relative_rejects_windows_roots_before_filesystem_resolution(value, syntax_path):
    with patch("gms_helpers.path_safety.Path", syntax_path):
        with pytest.raises(ValidationError, match="project-relative"):
            project_relative_path(value, project_root=WindowsSyntaxPath("D:/project"))


@pytest.mark.parametrize(
    "value",
    [
        "/scripts/scr/scr.yy",
        "\\scripts\\scr\\scr.yy",
        "scripts/../scripts/scr/scr.yy",
        "scripts\\..\\scripts\\scr\\scr.yy",
        "scripts/../../outside.yy",
        "scripts\\..\\..\\outside.yy",
    ],
)
def test_asset_lookup_rejects_windows_roots_before_filesystem_resolution(value, syntax_path):
    with (
        patch("gms_helpers.introspection.Path", syntax_path),
        patch("gms_helpers.path_safety.Path", syntax_path),
    ):
        assert get_asset_yy_path(WindowsSyntaxPath("D:/project"), value) is None


@pytest.mark.parametrize(
    "value",
    [
        "/scripts/scr/scr.yy",
        "\\scripts\\scr\\scr.yy",
        "scripts/../scripts/scr/scr.yy",
        "scripts\\..\\scripts\\scr\\scr.yy",
        "scripts/../../outside.yy",
        "scripts\\..\\..\\outside.yy",
    ],
)
@pytest.mark.parametrize("seam", ["asset_path", "asset_identifiers"])
def test_mcp_public_validation_rejects_windows_rooted_asset_inputs(value, seam, syntax_path):
    if seam == "asset_path":
        tool = "gm_workflow_duplicate"
        arguments = {"asset_path": value, "new_name": "scr_copy"}
        field = "asset_path"
    else:
        tool = "gm_texture_group_assign"
        arguments = {"group_name": "Default", "asset_identifiers": [value]}
        field = "asset_identifiers[0]"
    with patch("gms_mcp.server.validation.Path", syntax_path):
        errors = validate_mcp_tool_arguments(tool, arguments)
    assert field in {error["field"] for error in errors}


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_mcp_public_validation_preserves_relative_windows_separators(separator, syntax_path):
    value = separator.join(["scripts", "scr", "scr.yy"])
    with patch("gms_mcp.server.validation.Path", syntax_path):
        assert validate_mcp_tool_arguments("gm_workflow_duplicate", {"asset_path": value, "new_name": "scr_copy"}) == []
        assert (
            validate_mcp_tool_arguments(
                "gm_texture_group_assign", {"group_name": "Default", "asset_identifiers": [value]}
            )
            == []
        )


def test_helpers_allow_project_relative_paths_and_confine_resolved_links(tmp_path):
    project = tmp_path / "project"
    asset = project / "scripts" / "scr" / "scr.yy"
    asset.parent.mkdir(parents=True)
    asset.write_text("{}", encoding="utf-8")
    assert project_relative_path("scripts/scr/scr.yy", project_root=project) == asset.resolve()
    assert get_asset_yy_path(project, "scripts/scr/scr.yy") == asset.resolve()
    assert get_asset_yy_path(project, "scripts\\scr\\scr.yy") == asset.resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (project / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Host cannot create directory symlinks: {exc}")
    with pytest.raises(ValidationError, match="escapes"):
        project_relative_path("linked/private.yy", project_root=project)
    assert get_asset_yy_path(project, "linked/private.yy") is None


@pytest.mark.parametrize(
    "location",
    [
        "/tmp/outside.gml",
        "\\tmp\\outside.gml",
        "D:outside.gml",
        "scripts/../scripts/scr.gml",
        "scripts\\..\\scripts\\scr.gml",
        "scripts/../../outside.gml",
        "scripts\\..\\..\\outside.gml",
    ],
)
@pytest.mark.parametrize("section", ["definitions", "references", "file_metadata"])
def test_public_index_build_recovers_from_windows_rooted_cache_locations(tmp_path, location, section, syntax_path):
    project = tmp_path / "project"
    project.mkdir()
    cache = tmp_path / "cache.json"
    data = {"version": 3, "file_mtimes_ns": {}, "file_sizes": {}, "definitions": [], "references": []}
    if section == "file_metadata":
        data["file_mtimes_ns"] = {location: 1}
        data["file_sizes"] = {location: 1}
    elif section == "definitions":
        data[section] = [{"name": "unsafe", "kind": "function", "location": {"file": location, "line": 1}}]
    else:
        data[section] = [{"symbol": "unsafe", "location": {"file": location, "line": 1}}]
    cache.write_text(json.dumps(data), encoding="utf-8")
    index = GMLIndex(project)
    with (
        patch("gms_helpers.gml_index.index.Path", syntax_path),
        patch.object(GMLIndex, "cache_path", new_callable=PropertyMock, return_value=cache),
    ):
        report = index.build()
        assert report["status"] != "cached"
        assert index.find_definition("unsafe") == []
        assert index.find_references("unsafe") == []


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_public_index_build_preserves_legitimate_relative_cached_locations(tmp_path, separator, syntax_path):
    project = tmp_path / "project"
    project.mkdir()
    cache = tmp_path / "cache.json"
    location = separator.join(["scripts", "scr", "scr.gml"])
    cache.write_text(
        json.dumps(
            {
                "version": 3,
                "file_mtimes_ns": {},
                "file_sizes": {},
                "definitions": [{"name": "safe", "kind": "function", "location": {"file": location, "line": 1}}],
                "references": [],
            }
        ),
        encoding="utf-8",
    )
    index = GMLIndex(project)
    with (
        patch("gms_helpers.gml_index.index.Path", syntax_path),
        patch.object(GMLIndex, "cache_path", new_callable=PropertyMock, return_value=cache),
    ):
        assert index.build()["status"] == "cached"
        assert len(index.find_definition("safe")) == 1
