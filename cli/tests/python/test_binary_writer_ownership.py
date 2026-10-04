"""Generated project outputs must never claim an external editor's save."""

import json
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

from gms_helpers import transactions, workflow
from gms_helpers.asset_types import ScriptAsset, SoundAsset
from gms_helpers.exceptions import JSONParseError
from gms_helpers.sprite_import import import_strip_to_sprite
from gms_helpers.utils import create_dummy_png, load_json_loose, save_pretty_json_gm


@pytest.fixture
def project(tmp_path):
    (tmp_path / "fixture.yyp").write_text(json.dumps({"name": "fixture", "resources": [], "Folders": []}))
    return tmp_path


def external_save(path):
    thread = threading.Thread(target=lambda: path.write_bytes(b"external editor save"))
    thread.start()
    thread.join(5)
    assert not thread.is_alive()


@pytest.mark.parametrize(
    "writer,preexisting",
    [
        ("dummy-png", False),
        ("dummy-png", True),
        ("silent-wav", False),
        ("silent-wav", True),
        ("import-main", False),
        ("import-layer", False),
    ],
)
def test_binary_writer_does_not_claim_external_save_before_ownership_mark(project, writer, preexisting):
    source = project / "source.png"
    if writer.startswith("import-"):
        image = pytest.importorskip("PIL.Image")
        image.new("RGBA", (4, 2), "red").save(source)
    if preexisting:
        extension = "png" if writer == "dummy-png" else "wav"
        (project / f"generated.{extension}").write_bytes(b"original binary")
    tx = transactions.GameMakerProjectTransaction(project, "binary-ownership-race")
    tx.begin()
    original_mark = transactions.mark_transaction_path_owned
    png_count = 0
    raced = []

    def mark_after_editor_save(target, **kwargs):
        nonlocal png_count
        path = Path(target)
        if path.suffix == ".png":
            png_count += 1
        selected = (
            writer == "dummy-png"
            and path.name == "generated.png"
            or writer == "silent-wav"
            and path.name == "generated.wav"
            or writer == "import-main"
            and path.suffix == ".png"
            and png_count == 5
            or writer == "import-layer"
            and path.suffix == ".png"
            and png_count == 6
        )
        if selected:
            external_save(path)
            raced.append(path)
        return original_mark(target, **kwargs)

    try:
        with patch.object(transactions, "mark_transaction_path_owned", side_effect=mark_after_editor_save):
            if writer == "dummy-png":
                create_dummy_png(project / "generated.png", 2, 2)
            elif writer == "silent-wav":
                SoundAsset._write_silent_wav(project / "generated.wav")
            else:
                import_strip_to_sprite(project, "spr_imported", source, frame_width=2, frame_height=2)
        assert len(raced) == 1
        tx.capture_mutation_state()
        assert not tx.rollback()
        assert raced[0].read_bytes() == b"external editor save"
        assert tx.to_dict()["recovery_path"]
    finally:
        tx.cleanup()


@pytest.mark.parametrize("writer", ["dummy-png", "silent-wav"])
@pytest.mark.parametrize("preexisting", [False, True])
def test_binary_writer_without_conflict_restores_original_output(project, writer, preexisting):
    extension = "png" if writer == "dummy-png" else "wav"
    path = project / f"generated.{extension}"
    if preexisting:
        path.write_bytes(b"original binary")
    tx = transactions.GameMakerProjectTransaction(project, "binary-normal-rollback")
    tx.begin()
    try:
        if writer == "dummy-png":
            create_dummy_png(path, 2, 2)
            assert path.read_bytes().startswith(b"\x89PNG")
        else:
            SoundAsset._write_silent_wav(path)
            assert path.read_bytes().startswith(b"RIFF")
        tx.capture_mutation_state()
        assert tx.rollback()
        assert path.exists() == preexisting
        if preexisting:
            assert path.read_bytes() == b"original binary"
    finally:
        tx.cleanup()


def test_rename_does_not_replace_precise_ownership_with_live_external_content(project):
    relative = ScriptAsset().create_files(project, "old_script", "")
    yyp = project / "fixture.yyp"
    data = load_json_loose(yyp)
    data["resources"] = [{"id": {"name": "old_script", "path": relative}}]
    save_pretty_json_gm(yyp, data)
    external_path = project / "scripts/new_script/new_script.gml"
    original_save = workflow.save_pretty_json_gm

    def save_then_edit(path, data):
        original_save(path, data)
        if Path(path) == yyp:
            external_save(external_path)

    tx = transactions.GameMakerProjectTransaction(project, "rename-ownership-race")
    tx.begin()
    try:
        with (
            patch.object(workflow, "save_pretty_json_gm", side_effect=save_then_edit),
            patch("gms_helpers.reference_scanner.comprehensive_rename_asset", return_value=False),
        ):
            with pytest.raises(JSONParseError):
                workflow.rename_asset(project, relative, "new_script")
        tx.capture_mutation_state()
        assert not tx.rollback()
        assert external_path.read_bytes() == b"external editor save"
        assert tx.to_dict()["recovery_path"]
    finally:
        tx.cleanup()
