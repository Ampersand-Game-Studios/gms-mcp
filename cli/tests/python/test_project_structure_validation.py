"""Structural validation across supported GameMaker resource/schema families."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gms_helpers.asset_types import FolderAsset, ObjectAsset, SoundAsset, TileSetAsset
from gms_helpers.exceptions import GMSError, ValidationError
from gms_helpers.project_validation import resolve_asset_reference, validate_project_after_mutation
from gms_helpers.room_instance_helper import modify_instance
from gms_helpers.synthetic_project import create_synthetic_project
from gms_helpers.utils import load_json_loose, save_pretty_json_gm
from gms_helpers.event_helper import add_event
from gms_mcp.server.validation import validate_mcp_tool_arguments


FAMILIES = [
    ("scripts", "GMScript"),
    ("objects", "GMObject"),
    ("sprites", "GMSprite"),
    ("rooms", "GMRoom"),
    ("fonts", "GMFont"),
    ("shaders", "GMShader"),
    ("animcurves", "GMAnimCurve"),
    ("sounds", "GMSound"),
    ("paths", "GMPath"),
    ("tilesets", "GMTileSet"),
    ("timelines", "GMTimeline"),
    ("sequences", "GMSequence"),
    ("notes", "GMNotes"),
    ("extensions", "GMExtension"),
    ("particles", "GMParticleSystem"),
]
REFERENCES = [
    ("spriteId", "sprites", "GMSprite"),
    ("spriteMaskId", "sprites", "GMSprite"),
    ("parentObjectId", "objects", "GMObject"),
    ("collisionObjectId", "objects", "GMObject"),
    ("objectId", "objects", "GMObject"),
    ("parentRoom", "rooms", "GMRoom"),
    ("roomId", "rooms", "GMRoom"),
    ("sequenceId", "sequences", "GMSequence"),
    ("tilesetId", "tilesets", "GMTileSet"),
    ("tileSetId", "tilesets", "GMTileSet"),
    ("pathId", "paths", "GMPath"),
    ("soundId", "sounds", "GMSound"),
    ("fontId", "fonts", "GMFont"),
    ("animCurveId", "animcurves", "GMAnimCurve"),
    ("animationCurveId", "animcurves", "GMAnimCurve"),
    ("eventStubScript", "scripts", "GMScript"),
    ("particleSystemId", "particles", "GMParticleSystem"),
]


def project(root: Path) -> None:
    save_pretty_json_gm(
        root / "fixture.yyp",
        {
            "name": "fixture",
            "resourceType": "GMProject",
            "resources": [],
            "Folders": [
                {"name": "Assets", "%Name": "Assets", "folderPath": "folders/Assets.yy", "resourceType": "GMFolder"}
            ],
        },
    )


def asset(root: Path, prefix: str, name: str, resource_type: str, **fields: Any) -> dict[str, str]:
    ref = {"name": name, "path": f"{prefix}/{name.lower()}/{name}.yy"}
    data = {
        "name": name,
        "%Name": name,
        "resourceType": resource_type,
        "parent": {"name": "Assets", "path": "folders/Assets.yy"},
        **fields,
    }
    target = root / ref["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    save_pretty_json_gm(target, data)
    yyp = load_json_loose(root / "fixture.yyp")
    yyp["resources"].append({"id": ref})
    save_pretty_json_gm(root / "fixture.yyp", yyp)
    return ref


def rewrite(root: Path, ref: dict[str, str], **fields: Any) -> None:
    data = load_json_loose(root / ref["path"])
    data.update(fields)
    save_pretty_json_gm(root / ref["path"], data)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("prefix,resource_type", FAMILIES)
def test_registered_asset_families_and_type_mismatch(tmp_path, prefix, resource_type):
    project(tmp_path)
    ref = asset(tmp_path, prefix, "asset", resource_type)
    assert validate_project_after_mutation(tmp_path).success
    rewrite(tmp_path, ref, resourceType="GMUnknown")
    result = validate_project_after_mutation(tmp_path)
    assert not result.success
    assert any("resourceType" in error for error in result.errors)


@pytest.mark.parametrize("field,prefix,resource_type", REFERENCES)
def test_recursive_typed_reference_families(tmp_path, field, prefix, resource_type):
    project(tmp_path)
    target = asset(tmp_path, prefix, "target", resource_type)
    owner = asset(tmp_path, "notes", "owner", "GMNotes", nested=[{field: target}])
    assert validate_project_after_mutation(tmp_path).success
    wrong = asset(tmp_path, "notes", "wrong", "GMNotes")
    rewrite(tmp_path, owner, nested=[{field: wrong}])
    result = validate_project_after_mutation(tmp_path)
    assert not result.success
    assert any("wrong target type" in error for error in result.errors)


@pytest.mark.parametrize(
    "change",
    [
        {"name": "wrong"},
        {"%Name": "wrong"},
        {"parent": {"name": "Wrong", "path": "folders/Assets.yy"}},
        {"parent": {"name": "Missing", "path": "folders/Missing.yy"}},
        {"spriteId": {"name": "escape", "path": "../escape.yy"}},
    ],
)
def test_invalid_identity_parent_and_paths(tmp_path, change):
    project(tmp_path)
    ref = asset(tmp_path, "objects", "owner", "GMObject")
    rewrite(tmp_path, ref, **change)
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("key", ["parentObjectId", "parentRoom"])
def test_parent_cycles(tmp_path, key):
    project(tmp_path)
    prefix, resource_type = ("objects", "GMObject") if key == "parentObjectId" else ("rooms", "GMRoom")
    one = asset(tmp_path, prefix, "one", resource_type)
    two = asset(tmp_path, prefix, "two", resource_type, **{key: one})
    rewrite(tmp_path, one, **{key: two})
    assert any("cyclic" in e for e in validate_project_after_mutation(tmp_path).errors)


@pytest.mark.parametrize(
    "folder",
    [
        {"name": "Sub", "folderPath": "folders/Missing/Sub.yy", "resourceType": "GMFolder"},
        {"name": "Assets", "%Name": "Wrong", "folderPath": "folders/Assets.yy", "resourceType": "GMFolder"},
        {"name": "Assets", "folderPath": "folders/Assets.yy", "resourceType": "GMScript"},
    ],
)
def test_folder_hierarchy_and_identity(tmp_path, folder):
    project(tmp_path)
    data = load_json_loose(tmp_path / "fixture.yyp")
    data["Folders"] = [folder]
    save_pretty_json_gm(tmp_path / "fixture.yyp", data)
    assert not validate_project_after_mutation(tmp_path).success


def test_unknown_asset_location_cannot_hide_wrong_resource_type(tmp_path):
    project(tmp_path)
    asset(tmp_path, "unrecognized", "owner", "GMObject")
    assert not validate_project_after_mutation(tmp_path).success


def test_embedded_frame_ids_and_keyframe_ids_are_not_registered_assets(tmp_path):
    project(tmp_path)
    ref = asset(
        tmp_path,
        "sprites",
        "sprite",
        "GMSprite",
        frames=[
            {"name": "frame_uuid", "resourceType": "GMSpriteFrame"},
        ],
    )
    track = {
        "resourceType": "GMSpriteFramesTrack",
        "name": "frames",
        "keyframes": {
            "Keyframes": [
                {"id": "keyframe_uuid", "Channels": {"0": {"Id": {"name": "frame_uuid", "path": ref["path"]}}}}
            ]
        },
    }
    rewrite(tmp_path, ref, sequence={"resourceType": "GMSequence", "name": "sprite", "tracks": [track]})
    assert validate_project_after_mutation(tmp_path).success
    track["keyframes"]["Keyframes"][0]["Channels"]["0"]["Id"]["name"] = "missing_frame"
    rewrite(tmp_path, ref, sequence={"resourceType": "GMSequence", "tracks": [track]})
    assert any("embedded identity" in e for e in validate_project_after_mutation(tmp_path).errors)


@pytest.mark.parametrize(
    "track_type,prefix,resource_type",
    [
        ("GMSpriteTrack", "sprites", "GMSprite"),
        ("GMObjectTrack", "objects", "GMObject"),
        ("GMSequenceTrack", "sequences", "GMSequence"),
        ("GMAudioTrack", "sounds", "GMSound"),
        ("GMParticleTrack", "particles", "GMParticleSystem"),
    ],
)
def test_nested_sequence_track_reference_types(tmp_path, track_type, prefix, resource_type):
    project(tmp_path)
    target = asset(tmp_path, prefix, "target", resource_type)
    track = {
        "resourceType": track_type,
        "keyframes": {"Keyframes": [{"id": "uuid", "Channels": {"0": {"Id": target}}}]},
    }
    owner = asset(
        tmp_path, "sequences", "owner", "GMSequence", tracks=[{"resourceType": "GMGroupTrack", "tracks": [track]}]
    )
    assert validate_project_after_mutation(tmp_path).success
    wrong = asset(tmp_path, "notes", "wrong", "GMNotes")
    track["keyframes"]["Keyframes"][0]["Channels"]["0"]["Id"] = wrong
    rewrite(tmp_path, owner, tracks=[track])
    assert not validate_project_after_mutation(tmp_path).success


def test_property_references_resolve_embedded_properties(tmp_path):
    project(tmp_path)
    target = asset(
        tmp_path, "objects", "target", "GMObject", properties=[{"name": "speed", "resourceType": "GMObjectProperty"}]
    )
    owner = asset(
        tmp_path,
        "objects",
        "owner",
        "GMObject",
        parentObjectId=target,
        overriddenProperties=[{"objectId": target, "propertyId": {"name": "speed", "path": target["path"]}}],
    )
    assert validate_project_after_mutation(tmp_path).success
    rewrite(
        tmp_path,
        owner,
        overriddenProperties=[{"objectId": target, "propertyId": {"name": "missing", "path": target["path"]}}],
    )
    assert not validate_project_after_mutation(tmp_path).success


def test_nested_room_layers_items_and_creation_order(tmp_path):
    project(tmp_path)
    obj = asset(tmp_path, "objects", "obj", "GMObject")
    sprite = asset(tmp_path, "sprites", "sprite", "GMSprite")
    layer = {
        "name": "Group",
        "resourceType": "GMRFolderLayer",
        "layers": [
            {
                "name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [
                    {"name": "inst_a", "resourceType": "GMRInstance", "objectId": obj},
                ],
            },
            {
                "name": "Assets",
                "resourceType": "GMRAssetLayer",
                "sprites": [
                    {"name": "graphic_a", "resourceType": "GMRSpriteGraphic", "spriteId": sprite},
                ],
            },
        ],
    }
    ref = asset(tmp_path, "rooms", "room", "GMRoom", layers=[layer], instanceCreationOrder=["inst_a"])
    assert validate_project_after_mutation(tmp_path).success
    layer["layers"][1]["sprites"][0]["resourceType"] = "GMRInstance"
    rewrite(tmp_path, ref, layers=[layer])
    assert not validate_project_after_mutation(tmp_path).success


def test_creation_order_checks_the_referenced_room_not_only_instance_name(tmp_path):
    project(tmp_path)
    obj = asset(tmp_path, "objects", "obj", "GMObject")
    parent = asset(tmp_path, "rooms", "parent", "GMRoom")
    ref = asset(
        tmp_path,
        "rooms",
        "child",
        "GMRoom",
        parentRoom=parent,
        layers=[
            {
                "name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [{"name": "inst_a", "resourceType": "GMRInstance", "objectId": obj}],
            },
        ],
        instanceCreationOrder=[{"name": "inst_a", "path": parent["path"]}],
    )
    assert not validate_project_after_mutation(tmp_path).success
    rewrite(tmp_path, ref, instanceCreationOrder=[{"name": "inst_a", "path": ref["path"]}])
    assert validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("asset_factory", [ObjectAsset, TileSetAsset])
@pytest.mark.parametrize("bad_target", ["missing", "note"])
def test_creation_reference_preflight_has_no_writes(tmp_path, asset_factory, bad_target):
    project(tmp_path)
    asset(tmp_path, "notes", "note", "GMNotes")
    before = snapshot(tmp_path)
    with pytest.raises(GMSError):
        asset_factory().create_files(tmp_path, "new_asset", "", sprite_id=bad_target)
    assert snapshot(tmp_path) == before


def test_modification_uses_registered_case_preserving_reference_and_rejects_missing(tmp_path, monkeypatch):
    project(tmp_path)
    obj = asset(tmp_path, "objects", "o_Player", "GMObject")
    room = asset(
        tmp_path,
        "rooms",
        "r_Room",
        "GMRoom",
        layers=[
            {
                "name": "Instances",
                "resourceType": "GMRInstanceLayer",
                "instances": [{"name": "inst_a", "resourceType": "GMRInstance", "objectId": obj}],
            },
        ],
        instanceCreationOrder=["inst_a"],
    )
    monkeypatch.chdir(tmp_path)
    assert modify_instance("r_Room", "inst_a", object_name="o_Player")
    data = load_json_loose(tmp_path / room["path"])
    assert data["layers"][0]["instances"][0]["objectId"] == obj
    before = snapshot(tmp_path)
    with pytest.raises(GMSError):
        modify_instance("r_Room", "inst_a", object_name="missing", x=100)
    assert snapshot(tmp_path) == before


def test_reference_resolution_rejects_duplicate_and_unsafe_registration(tmp_path):
    project(tmp_path)
    ref = asset(tmp_path, "objects", "obj", "GMObject")
    yyp = load_json_loose(tmp_path / "fixture.yyp")
    yyp["resources"].append({"id": ref})
    save_pretty_json_gm(tmp_path / "fixture.yyp", yyp)
    with pytest.raises(ValidationError):
        resolve_asset_reference(tmp_path, "obj", "GMObject")


@pytest.mark.parametrize("ide_version", ["2024.14.3.217", "2026.0.0.16"])
def test_runtime_fixture_families_remain_valid(tmp_path, ide_version):
    root = tmp_path / "synthetic"
    create_synthetic_project(root, project_name="fixture", ide_version=ide_version)
    result = validate_project_after_mutation(root)
    assert result.success, result.errors


@pytest.mark.parametrize(
    "tool,args",
    [
        ("gm_room_instance_add", {"room_name": "r_room", "object_name": "o_missing", "x": 0, "y": 0}),
        ("gm_event_add", {"object": "o_missing", "event": "create"}),
        ("gm_sprite_add_frame", {"sprite_path": "sprites/spr_missing/spr_missing.yy"}),
    ],
)
def test_mcp_preflight_resolves_existing_references(tmp_path, tool, args):
    project(tmp_path)
    asset(tmp_path, "rooms", "r_room", "GMRoom")
    before = snapshot(tmp_path)
    assert validate_mcp_tool_arguments(tool, {"project_root": str(tmp_path), **args})
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("state", ["unregistered", "wrong_type", "wrong_name"])
def test_event_edit_rejects_invalid_owner_without_writes(tmp_path, state):
    project(tmp_path)
    ref = asset(tmp_path, "objects", "o_owner", "GMObject", eventList=[])
    if state == "unregistered":
        yyp = load_json_loose(tmp_path / "fixture.yyp")
        yyp["resources"] = []
        save_pretty_json_gm(tmp_path / "fixture.yyp", yyp)
    elif state == "wrong_type":
        rewrite(tmp_path, ref, resourceType="GMSprite")
    else:
        rewrite(tmp_path, ref, name="o_wrong")
    before = snapshot(tmp_path)
    with pytest.raises(GMSError):
        add_event("o_owner", "create", project_root=tmp_path)
    assert snapshot(tmp_path) == before


def test_groups_and_serialized_configuration_reference_formats(tmp_path):
    project(tmp_path)
    yyp = load_json_loose(tmp_path / "fixture.yyp")
    yyp["TextureGroups"] = [
        {"name": "Default", "resourceType": "GMTextureGroup", "groupParent": None},
        {
            "name": "Custom",
            "resourceType": "GMTextureGroup",
            "groupParent": "Default",
            "ConfigValues": {"desktop": {"groupParent": "Default"}},
        },
    ]
    save_pretty_json_gm(tmp_path / "fixture.yyp", yyp)
    ref = asset(
        tmp_path,
        "sprites",
        "sprite",
        "GMSprite",
        textureGroupId={"name": "Custom", "path": "texturegroups/Custom"},
        ConfigValues={"desktop": {"textureGroupId": '{ "name":"Custom", "path":"texturegroups/Custom", }'}},
    )
    assert validate_project_after_mutation(tmp_path).success
    rewrite(
        tmp_path,
        ref,
        ConfigValues={"desktop": {"textureGroupId": '{"name":"Missing", "path":"texturegroups/Missing"}'}},
    )
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize(
    "field,items",
    [
        ("frames", [{"name": "duplicate", "resourceType": "GMSpriteFrame"}] * 2),
        ("frames", [{"name": "frame", "%Name": "wrong", "resourceType": "GMSpriteFrame"}]),
        ("frames", [{"name": "frame", "resourceType": "GMObjectProperty"}]),
        ("properties", [{"name": "duplicate", "resourceType": "GMObjectProperty"}] * 2),
        ("properties", [{"name": "property", "%Name": "wrong", "resourceType": "GMObjectProperty"}]),
    ],
)
def test_embedded_frame_and_property_identity_validation(tmp_path, field, items):
    project(tmp_path)
    prefix, resource_type = ("sprites", "GMSprite") if field == "frames" else ("objects", "GMObject")
    asset(tmp_path, prefix, "owner", resource_type, **{field: items})
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize(
    "entry",
    [
        {"eventType": 3, "eventNum": 3},
        {"eventType": 2, "eventNum": 12},
        {"eventType": 0, "eventNum": 0, "resourceType": "GMScript"},
        {"eventType": True, "eventNum": 0},
        {"eventType": 4, "eventNum": 0, "collisionObjectId": None},
    ],
)
def test_event_schema_subtypes_and_collision_requirements(tmp_path, entry):
    project(tmp_path)
    asset(tmp_path, "objects", "owner", "GMObject", eventList=[entry])
    assert not validate_project_after_mutation(tmp_path).success


def test_property_reference_cannot_target_a_room_containing_property_shaped_data(tmp_path):
    project(tmp_path)
    room = asset(
        tmp_path, "rooms", "room", "GMRoom", properties=[{"name": "speed", "resourceType": "GMObjectProperty"}]
    )
    asset(
        tmp_path,
        "objects",
        "obj",
        "GMObject",
        overriddenProperties=[{"propertyId": {"name": "speed", "path": room["path"]}}],
    )
    assert not validate_project_after_mutation(tmp_path).success


def test_sequence_sprite_track_requires_asset_identity_not_a_frame_uuid(tmp_path):
    project(tmp_path)
    sprite = asset(
        tmp_path, "sprites", "sprite", "GMSprite", frames=[{"name": "frame", "resourceType": "GMSpriteFrame"}]
    )
    asset(
        tmp_path,
        "sequences",
        "sequence",
        "GMSequence",
        tracks=[
            {
                "resourceType": "GMSpriteTrack",
                "keyframes": {
                    "Keyframes": [
                        {"id": "kf", "Channels": {"0": {"Id": {"name": "frame", "path": sprite["path"]}}}},
                    ]
                },
            },
        ],
    )
    assert not validate_project_after_mutation(tmp_path).success


def test_parent_reference_uses_registered_folder_identity(tmp_path):
    project(tmp_path)
    yyp = load_json_loose(tmp_path / "fixture.yyp")
    yyp["Folders"][0]["name"] = "Different display name"
    yyp["Folders"][0]["%Name"] = "Different display name"
    save_pretty_json_gm(tmp_path / "fixture.yyp", yyp)
    path = ObjectAsset().create_files(tmp_path, "obj", "folders/Assets.yy")
    assert load_json_loose(tmp_path / path)["parent"]["name"] == "Different display name"


@pytest.mark.parametrize("width,height", [(0, 10), (10, -1), (True, 10), (10.5, 10)])
def test_room_creation_rejects_invalid_dimensions_before_default_folder_writes(tmp_path, width, height):
    from gms_helpers.asset_types import RoomAsset

    project(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises((ValueError, ValidationError)):
        RoomAsset().create_files(tmp_path, "room", "", width=width, height=height)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("family", ["frames", "properties"])
def test_embedded_identities_must_be_declared_in_the_correct_collection(tmp_path, family):
    project(tmp_path)
    prefix, resource_type = ("sprites", "GMSprite") if family == "frames" else ("objects", "GMObject")
    embedded_type = "GMSpriteFrame" if family == "frames" else "GMObjectProperty"
    target = asset(tmp_path, prefix, "target", resource_type, unrelated={"name": "fake", "resourceType": embedded_type})
    if family == "frames":
        rewrite(
            tmp_path,
            target,
            sequence={
                "resourceType": "GMSequence",
                "tracks": [
                    {
                        "resourceType": "GMSpriteFramesTrack",
                        "keyframes": {
                            "Keyframes": [
                                {"id": "kf", "Channels": {"0": {"Id": {"name": "fake", "path": target["path"]}}}},
                            ]
                        },
                    },
                ],
            },
        )
    else:
        asset(
            tmp_path,
            "objects",
            "owner",
            "GMObject",
            overriddenProperties=[
                {"objectId": target, "propertyId": {"name": "fake", "path": target["path"]}},
            ],
        )
    assert not validate_project_after_mutation(tmp_path).success


def test_custom_timeline_moments_write_every_referenced_code_file(tmp_path):
    from gms_helpers.asset_types import TimelineAsset

    project(tmp_path)
    path = TimelineAsset().create_files(
        tmp_path, "timeline", "folders/Assets.yy", moments=[{"moment": 5}, {"moment": 10}]
    )
    yyp = load_json_loose(tmp_path / "fixture.yyp")
    yyp["resources"].append({"id": {"name": "timeline", "path": path}})
    save_pretty_json_gm(tmp_path / "fixture.yyp", yyp)
    folder = (tmp_path / path).parent
    assert (folder / "moment_5.gml").is_file()
    assert (folder / "moment_10.gml").is_file()
    assert validate_project_after_mutation(tmp_path).success
    (folder / "moment_5.gml").unlink()
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("channels", [None, [], "invalid"])
def test_sequence_keyframe_channels_are_keyed_objects(tmp_path, channels):
    project(tmp_path)
    asset(
        tmp_path,
        "sequences",
        "sequence",
        "GMSequence",
        tracks=[
            {"resourceType": "GMRealTrack", "keyframes": {"Keyframes": [{"id": "kf", "Channels": channels}]}},
        ],
    )
    assert not validate_project_after_mutation(tmp_path).success


def test_room_asset_items_have_unique_local_identities(tmp_path):
    project(tmp_path)
    sprite = asset(tmp_path, "sprites", "sprite", "GMSprite")
    asset(
        tmp_path,
        "rooms",
        "room",
        "GMRoom",
        layers=[
            {
                "name": "Assets",
                "resourceType": "GMRAssetLayer",
                "sprites": [
                    {"name": "graphic", "resourceType": "GMRSpriteGraphic", "spriteId": sprite},
                    {"name": "graphic", "resourceType": "GMRSpriteGraphic", "spriteId": sprite},
                ],
            },
        ],
    )
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("factory", [ObjectAsset, FolderAsset])
def test_creation_rejects_escaping_yyp_symlink_without_writes(tmp_path, factory):
    outside = tmp_path / "outside"
    outside.mkdir()
    project(outside)
    root = tmp_path / "project"
    root.mkdir()
    (root / "fixture.yyp").symlink_to(outside / "fixture.yyp")
    before = snapshot(tmp_path)
    with pytest.raises((GMSError, ValueError)):
        factory().create_files(root, "new_asset", "")
    assert (root / "fixture.yyp").is_symlink()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("path", [None, 5, [], "../escape.yy"])
def test_reference_resolution_reports_invalid_registration_paths(tmp_path, path):
    project(tmp_path)
    data = load_json_loose(tmp_path / "fixture.yyp")
    data["resources"] = [{"id": {"name": "obj", "path": path}}]
    save_pretty_json_gm(tmp_path / "fixture.yyp", data)
    with pytest.raises(ValidationError):
        resolve_asset_reference(tmp_path, "obj", "GMObject")


@pytest.mark.parametrize("nodes", [None, {}, "room", [None], [{}], [{"roomId": None}]])
def test_room_order_requires_an_array_of_room_reference_nodes(tmp_path, nodes):
    project(tmp_path)
    data = load_json_loose(tmp_path / "fixture.yyp")
    data["RoomOrderNodes"] = nodes
    save_pretty_json_gm(tmp_path / "fixture.yyp", data)
    result = validate_project_after_mutation(tmp_path)
    assert not result.success
    assert any("RoomOrderNodes" in error for error in result.errors)


@pytest.mark.parametrize("backslashes", [False, True])
def test_room_order_rejects_duplicate_registered_rooms(tmp_path, backslashes):
    project(tmp_path)
    room = asset(tmp_path, "rooms", "room", "GMRoom")
    second_reference = dict(room)
    if backslashes:
        second_reference["path"] = room["path"].replace("/", "\\")
    data = load_json_loose(tmp_path / "fixture.yyp")
    data["RoomOrderNodes"] = [{"roomId": room}, {"roomId": second_reference}]
    save_pretty_json_gm(tmp_path / "fixture.yyp", data)
    result = validate_project_after_mutation(tmp_path)
    assert not result.success
    assert any("duplicate room-order" in error for error in result.errors)


def test_distinct_room_order_references_are_valid(tmp_path):
    project(tmp_path)
    first = asset(tmp_path, "rooms", "first", "GMRoom")
    second = asset(tmp_path, "rooms", "second", "GMRoom")
    data = load_json_loose(tmp_path / "fixture.yyp")
    data["RoomOrderNodes"] = [{"roomId": first}, {"roomId": second}]
    save_pretty_json_gm(tmp_path / "fixture.yyp", data)
    result = validate_project_after_mutation(tmp_path)
    assert result.success, result.errors


SCALAR_FILE_FIELDS = [
    ("sounds", "GMSound", "soundFile", "clip.wav", "sounds/item/clip.wav"),
    ("fonts", "GMFont", "TTFName", "font.ttf", "fonts/item/font.ttf"),
    ("fonts", "GMFont", "texture", "atlas.png", "fonts/item/atlas.png"),
    ("rooms", "GMRoom", "creationCodeFile", "${project_dir}/rooms/item/code.gml", "rooms/item/code.gml"),
    ("rooms", "GMRoom", "creationCodeFile", "rooms/item/code.gml", "rooms/item/code.gml"),
    ("rooms", "GMRoom", "creationCodeFile", "code.gml", "rooms/item/code.gml"),
    ("extensions", "GMExtension", "helpfile", "help.html", "extensions/item/help.html"),
]


@pytest.mark.parametrize("prefix,resource_type,key,value,relative", SCALAR_FILE_FIELDS)
@pytest.mark.parametrize(
    "damage", ["valid", "missing", "absolute", "traversal", "directory", "external-symlink", "wrong-type"]
)
def test_schema_scalar_file_references(tmp_path, prefix, resource_type, key, value, relative, damage):
    project(tmp_path)
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if damage == "directory":
        target.mkdir()
    elif damage == "external-symlink":
        target.symlink_to(tmp_path.parent / "outside")
    elif damage != "missing":
        target.write_bytes(b"fixture companion")
    if damage == "absolute":
        value = str(target)
    elif damage == "traversal":
        value = "../" + value
    elif damage == "wrong-type":
        value = 7
    asset(tmp_path, prefix, "item", resource_type, **{key: value})
    result = validate_project_after_mutation(tmp_path)
    assert result.success == (damage == "valid"), result.errors


@pytest.mark.parametrize("value", ["bad.txt", "nested/clip.wav", "nested\\clip.wav"])
def test_sound_file_is_an_audio_basename(tmp_path, value):
    project(tmp_path)
    ref = asset(tmp_path, "sounds", "item", "GMSound", soundFile=value)
    target = (tmp_path / ref["path"]).parent / value.replace("\\", "/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fixture")
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("prefix,resource_type,key,value,relative", SCALAR_FILE_FIELDS)
def test_optional_scalar_file_defaults_remain_valid(tmp_path, prefix, resource_type, key, value, relative):
    project(tmp_path)
    asset(tmp_path, prefix, "item", resource_type, **{key: ""})
    assert validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("damage", ["valid", "missing", "absolute", "traversal", "wrong-extension"])
def test_nested_room_instance_creation_code_reference(tmp_path, damage):
    project(tmp_path)
    obj = asset(tmp_path, "objects", "obj", "GMObject")
    filename = "instance.gml" if damage != "wrong-extension" else "instance.png"
    if damage == "absolute":
        filename = str(tmp_path / "instance.gml")
    elif damage == "traversal":
        filename = "../instance.gml"
    room = asset(
        tmp_path,
        "rooms",
        "item",
        "GMRoom",
        layers=[
            {
                "name": "Folder",
                "resourceType": "GMRFolderLayer",
                "layers": [
                    {
                        "name": "Instances",
                        "resourceType": "GMRInstanceLayer",
                        "instances": [
                            {
                                "name": "inst",
                                "resourceType": "GMRInstance",
                                "objectId": obj,
                                "creationCodeFile": filename,
                            }
                        ],
                    }
                ],
            }
        ],
        instanceCreationOrder=["inst"],
    )
    if damage != "missing":
        target = (tmp_path / room["path"]).parent / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture code")
    result = validate_project_after_mutation(tmp_path)
    assert result.success == (damage == "valid"), result.errors


@pytest.mark.parametrize(
    "damage", ["valid", "missing", "absolute", "traversal", "type", "identity", "duplicate", "shape"]
)
def test_yyp_included_file_references(tmp_path, damage):
    project(tmp_path)
    entry = {
        "name": "config.bin",
        "%Name": "config.bin",
        "filePath": "datafiles/config",
        "resourceType": "GMIncludedFile",
    }
    target = tmp_path / "datafiles/config/config.bin"
    target.parent.mkdir(parents=True)
    if damage != "missing":
        target.write_bytes(b"fixture")
    if damage == "absolute":
        entry["filePath"] = str(target.parent)
    elif damage == "traversal":
        entry["name"] = "../config.bin"
        entry["%Name"] = "../config.bin"
    elif damage == "type":
        entry["resourceType"] = "GMObject"
    elif damage == "identity":
        entry["%Name"] = "different.bin"
    data = load_json_loose(tmp_path / "fixture.yyp")
    data["IncludedFiles"] = [entry, entry] if damage == "duplicate" else {} if damage == "shape" else [entry]
    save_pretty_json_gm(tmp_path / "fixture.yyp", data)
    result = validate_project_after_mutation(tmp_path)
    assert result.success == (damage == "valid"), result.errors


@pytest.mark.parametrize(
    "damage", ["valid", "missing", "absolute", "traversal", "proxy-missing", "proxy-traversal", "shape"]
)
def test_extension_packaged_file_and_proxy_references(tmp_path, damage):
    project(tmp_path)
    filename = "library.dll"
    if damage == "absolute":
        filename = str(tmp_path / "library.dll")
    elif damage == "traversal":
        filename = "../library.dll"
    proxy = "other.so" if damage != "proxy-traversal" else "../other.so"
    files = [
        {
            "filename": filename,
            "name": filename,
            "%Name": filename,
            "resourceType": "GMExtensionFile",
            "ProxyFiles": [{"name": proxy, "%Name": proxy, "resourceType": "GMProxyFile"}],
        }
    ]
    ref = asset(tmp_path, "extensions", "item", "GMExtension", files={} if damage == "shape" else files)
    directory = (tmp_path / ref["path"]).parent
    if damage != "missing":
        (directory / filename).write_bytes(b"fixture library")
    if damage != "proxy-missing":
        (directory / proxy).write_bytes(b"fixture proxy")
    result = validate_project_after_mutation(tmp_path)
    assert result.success == (damage == "valid"), result.errors


def test_extension_virtual_native_container_and_generated_options_are_not_packaged_files(tmp_path):
    project(tmp_path)
    asset(
        tmp_path,
        "extensions",
        "item",
        "GMExtension",
        optionsFile="options.json",
        files=[
            {
                "filename": "container.ext",
                "name": "container.ext",
                "resourceType": "GMExtensionFile",
                "kind": 4,
                "origname": "C:\\original\\library.dll",
                "ProxyFiles": [],
            }
        ],
    )
    result = validate_project_after_mutation(tmp_path)
    assert result.success, result.errors


def test_scalar_file_safety_is_checked_before_creating_generated_sound_files(tmp_path, monkeypatch):
    project(tmp_path)
    creator = SoundAsset()
    original = creator.create_yy_data

    def unsafe(*args, **kwargs):
        data = original(*args, **kwargs)
        data["soundFile"] = "../escape.wav"
        return data

    monkeypatch.setattr(creator, "create_yy_data", unsafe)
    before = snapshot(tmp_path)
    with pytest.raises(ValidationError):
        creator.create_files(tmp_path, "snd_new", "")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("inherit_code", [False, True])
@pytest.mark.parametrize("value", ["${project_dir}/rooms/old/code.gml", "../escape.gml"])
def test_inherited_room_ignores_absent_local_code_but_never_unsafe_paths(tmp_path, inherit_code, value):
    project(tmp_path)
    parent = asset(tmp_path, "rooms", "parent", "GMRoom")
    asset(tmp_path, "rooms", "item", "GMRoom", creationCodeFile=value, inheritCode=inherit_code, parentRoom=parent)
    result = validate_project_after_mutation(tmp_path)
    assert result.success == (inherit_code and not value.startswith("..")), result.errors


@pytest.mark.parametrize("prefix,resource_type,key,value,relative", SCALAR_FILE_FIELDS)
def test_scalar_file_configuration_overrides_are_checked(tmp_path, prefix, resource_type, key, value, relative):
    project(tmp_path)
    asset(tmp_path, prefix, "item", resource_type, ConfigValues={"desktop": {key: value}})
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("value", ["../escape.json", "/tmp/options.json", "options.txt", "C:options.json"])
def test_generated_extension_options_remain_path_and_type_checked(tmp_path, value):
    project(tmp_path)
    asset(tmp_path, "extensions", "item", "GMExtension", optionsFile=value)
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("field", ["soundFile", "TTFName", "creationCodeFile", "optionsFile"])
def test_file_like_custom_fields_are_not_assigned_another_resource_schema(tmp_path, field):
    project(tmp_path)
    asset(tmp_path, "objects", "item", "GMObject", customData={field: "/original/input/path"})
    assert validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("collection", ["files", "ProxyFiles"])
@pytest.mark.parametrize("entry", [None, {}, {"resourceType": "GMObject"}])
def test_extension_file_collections_reject_malformed_entries(tmp_path, collection, entry):
    project(tmp_path)
    fields = {"files": [entry]}
    if collection == "ProxyFiles":
        fields = {"files": [{"filename": "native.ext", "kind": 4, "ProxyFiles": [entry]}]}
    asset(tmp_path, "extensions", "item", "GMExtension", **fields)
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("proxy", [False, True])
def test_extension_file_configuration_references_do_not_escape(tmp_path, proxy):
    project(tmp_path)
    fields = {"filename": "native.ext", "kind": 4, "ConfigValues": {"desktop": {"filename": "../escape.dll"}}}
    if proxy:
        fields = {
            "filename": "native.ext",
            "kind": 4,
            "ProxyFiles": [{"name": "proxy.dll", "ConfigValues": {"desktop": {"name": "../escape.dll"}}}],
        }
    ref = asset(tmp_path, "extensions", "item", "GMExtension", files=[fields])
    if proxy:
        (tmp_path / ref["path"]).parent.joinpath("proxy.dll").write_bytes(b"fixture")
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("shape", [None, "invalid", [None], [{}]])
def test_yyp_included_file_collections_reject_malformed_shapes(tmp_path, shape):
    project(tmp_path)
    data = load_json_loose(tmp_path / "fixture.yyp")
    data["IncludedFiles"] = shape
    save_pretty_json_gm(tmp_path / "fixture.yyp", data)
    assert not validate_project_after_mutation(tmp_path).success


@pytest.mark.parametrize("ide_version", ["2024.14.3.217", "2026.0.0.16"])
def test_runtime_fixture_accepts_generated_sound_and_included_file_defaults(tmp_path, ide_version):
    create_synthetic_project(tmp_path, project_name="fixture", ide_version=ide_version)
    relative = SoundAsset().create_files(tmp_path, "snd_fixture", "")
    yyp = tmp_path / "fixture.yyp"
    data = load_json_loose(yyp)
    data["resources"].append({"id": {"name": "snd_fixture", "path": relative}})
    data["IncludedFiles"] = [{"name": "input.bin", "filePath": "datafiles", "resourceType": "GMIncludedFile"}]
    (tmp_path / "datafiles").mkdir(exist_ok=True)
    (tmp_path / "datafiles/input.bin").write_bytes(b"fixture")
    save_pretty_json_gm(yyp, data)
    result = validate_project_after_mutation(tmp_path)
    assert result.success, result.errors
