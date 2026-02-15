#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path


class TestAssetFormatDetection(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.project_root = Path(self._td.name)
        for d in ("objects", "scripts", "sprites", "rooms"):
            (self.project_root / d).mkdir(parents=True, exist_ok=True)
        # Minimal .yyp so BaseAsset can resolve parent_path
        (self.project_root / "TestProject.yyp").write_text("{}", encoding="utf-8")

    def tearDown(self):
        try:
            self._td.cleanup()
        except Exception:
            pass

    def test_object_tag_version_matches_existing_project_convention(self):
        from gms_helpers.assets import ObjectAsset
        from gms_helpers.utils import load_json

        # Seed an existing object with $GMObject = \"v1\"
        existing_dir = self.project_root / "objects" / "o_existing"
        existing_dir.mkdir(parents=True, exist_ok=True)
        (existing_dir / "o_existing.yy").write_text(
            json.dumps(
                {
                    "$GMObject": "v1",
                    "%Name": "o_existing",
                    "name": "o_existing",
                    "resourceType": "GMObject",
                    "resourceVersion": "2.0",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        asset = ObjectAsset()
        rel = asset.create_files(self.project_root, "o_new", "", create_event=False)
        self.assertTrue(rel.endswith("objects/o_new/o_new.yy"))

        data = load_json(self.project_root / rel)
        self.assertEqual(data.get("$GMObject"), "v1")

    def test_script_tag_version_matches_existing_project_convention(self):
        from gms_helpers.assets import ScriptAsset
        from gms_helpers.utils import load_json

        # Seed an existing script with $GMScript = \"\" (empty string)
        existing_dir = self.project_root / "scripts" / "scr_existing"
        existing_dir.mkdir(parents=True, exist_ok=True)
        (existing_dir / "scr_existing.yy").write_text(
            json.dumps(
                {
                    "$GMScript": "",
                    "%Name": "scr_existing",
                    "name": "scr_existing",
                    "resourceType": "GMScript",
                    "resourceVersion": "2.0",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        asset = ScriptAsset()
        rel = asset.create_files(self.project_root, "scr_new", "", is_constructor=False)
        self.assertTrue(rel.endswith("scripts/scr_new/scr_new.yy"))

        data = load_json(self.project_root / rel)
        self.assertEqual(data.get("$GMScript"), "")


if __name__ == "__main__":
    unittest.main()

