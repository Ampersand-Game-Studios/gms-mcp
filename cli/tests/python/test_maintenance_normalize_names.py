import json
from pathlib import Path

from gms_helpers.maintenance.normalize_names import normalize_asset_names, plan_name_normalization
from gms_helpers.utils import load_json_loose


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_project(root: Path) -> Path:
    yyp = root / "TemplateGame.yyp"
    _write_json(
        yyp,
        {
            "resources": [
                {
                    "id": {
                        "name": "room1",
                        "path": "rooms/room1/room1.yy",
                    }
                }
            ],
            "Folders": [],
        },
    )
    _write_json(
        root / "rooms" / "room1" / "room1.yy",
        {
            "$GMRoom": "v1",
            "%Name": "room1",
            "name": "room1",
            "parent": {"name": "Rooms", "path": "folders/Rooms.yy"},
            "resourceType": "GMRoom",
            "resourceVersion": "2.0",
        },
    )
    return yyp


def test_plan_name_normalization_is_dry_run_for_gm_cli_room_template(tmp_path):
    _make_project(tmp_path)

    result = plan_name_normalization(tmp_path)

    assert result["ok"] is True
    assert result["planned"] == [
        {
            "asset_type": "room",
            "asset_name": "room1",
            "asset_path": "rooms/room1/room1.yy",
            "target_name": "r_room1",
        }
    ]
    assert (tmp_path / "rooms" / "room1" / "room1.yy").exists()


def test_normalize_asset_names_applies_gm_cli_room_template_fix(tmp_path):
    yyp_path = _make_project(tmp_path)

    result = normalize_asset_names(tmp_path, fix=True)

    assert result["ok"] is True
    assert result["changed_count"] == 1
    assert not (tmp_path / "rooms" / "room1").exists()
    new_room_path = tmp_path / "rooms" / "r_room1" / "r_room1.yy"
    assert new_room_path.exists()

    yyp_data = load_json_loose(yyp_path)
    assert yyp_data["resources"][0]["id"] == {
        "name": "r_room1",
        "path": "rooms/r_room1/r_room1.yy",
    }

    room_data = load_json_loose(new_room_path)
    assert room_data["name"] == "r_room1"
    assert room_data["%Name"] == "r_room1"


def test_normalize_asset_names_skips_existing_target(tmp_path):
    _make_project(tmp_path)
    _write_json(
        tmp_path / "TemplateGame.yyp",
        {
            "resources": [
                {"id": {"name": "room1", "path": "rooms/room1/room1.yy"}},
                {"id": {"name": "r_room1", "path": "rooms/r_room1/r_room1.yy"}},
            ],
            "Folders": [],
        },
    )

    result = normalize_asset_names(tmp_path, fix=False, asset_type="room")

    assert result["ok"] is True
    assert result["planned"] == []
    assert result["skipped"][0]["reason"] == "Target name 'r_room1' already exists."
