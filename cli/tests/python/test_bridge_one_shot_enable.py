#!/usr/bin/env python3
import asyncio
import json
import tempfile
import unittest
from pathlib import Path


def _unwrap_call_tool(result):
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict) and "result" in result[1]:
        return result[1]["result"]
    if isinstance(result, dict):
        return result
    raise AssertionError(f"Unexpected call_tool return type: {type(result)} ({result!r})")


class TestBridgeOneShotEnable(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.project_root = Path(self._td.name)
        for d in ("objects", "sprites", "scripts", "rooms", "folders"):
            (self.project_root / d).mkdir(parents=True, exist_ok=True)

        # Create a startup room and a minimal .yyp with RoomOrderNodes.
        yyp = {
            "$GMProject": "",
            "%Name": "TestProject",
            "name": "TestProject",
            "resources": [
                {"id": {"name": "r_main", "path": "rooms/r_main/r_main.yy"}},
            ],
            "folders": [],
            "RoomOrderNodes": [
                {"roomId": {"name": "r_main", "path": "rooms/r_main/r_main.yy"}},
            ],
            "resourceType": "GMProject",
            "resourceVersion": "2.0",
        }
        (self.project_root / "TestProject.yyp").write_text(json.dumps(yyp, indent=2), encoding="utf-8")

        from gms_helpers.assets import RoomAsset

        RoomAsset().create_files(self.project_root, "r_main", "", width=800, height=600)

        from gms_mcp.gamemaker_mcp_server import build_server

        self.mcp = build_server()

    def tearDown(self):
        try:
            self._td.cleanup()
        except Exception:
            pass

    def test_one_shot_enables_bridge_and_patches_instance_creation_order(self):
        from gms_helpers.utils import load_json_loose

        out = asyncio.run(
            self.mcp.call_tool(
                "gm_bridge_enable_one_shot",
                {"project_root": str(self.project_root)},
            )
        )
        result = _unwrap_call_tool(out)
        self.assertTrue(result.get("ok"), msg=result.get("error") or result)
        instance_id = result.get("instance_id")
        self.assertTrue(instance_id)
        self.assertEqual(result.get("room_name"), "r_main")

        # Bridge assets installed
        self.assertTrue((self.project_root / "objects" / "__mcp_bridge" / "__mcp_bridge.yy").exists())

        room_file = self.project_root / "rooms" / "r_main" / "r_main.yy"
        room_data = load_json_loose(room_file)
        self.assertIsInstance(room_data, dict)

        # Instance exists in an instance layer
        found_instances = []
        for layer in room_data.get("layers", []) or []:
            if not isinstance(layer, dict) or layer.get("resourceType") != "GMRInstanceLayer":
                continue
            for inst in layer.get("instances", []) or []:
                if not isinstance(inst, dict):
                    continue
                obj = inst.get("objectId") or {}
                if isinstance(obj, dict) and obj.get("name") == "__mcp_bridge":
                    found_instances.append(inst)

        self.assertEqual(len(found_instances), 1, msg=str(found_instances))
        self.assertEqual(found_instances[0].get("name"), instance_id)

        # instanceCreationOrder contains this instance id
        ico = room_data.get("instanceCreationOrder", [])
        self.assertIsInstance(ico, list)
        self.assertTrue(
            any(
                (isinstance(e, str) and e == instance_id)
                or (isinstance(e, dict) and e.get("name") == instance_id)
                for e in ico
            ),
            msg=str(ico),
        )

        # Idempotent: calling again should not create a second instance.
        out2 = asyncio.run(
            self.mcp.call_tool(
                "gm_bridge_enable_one_shot",
                {"project_root": str(self.project_root)},
            )
        )
        result2 = _unwrap_call_tool(out2)
        self.assertTrue(result2.get("ok"), msg=result2.get("error") or result2)
        self.assertEqual(result2.get("instance_id"), instance_id)

        room_data2 = load_json_loose(room_file)
        bridge_instances = []
        for layer in room_data2.get("layers", []) or []:
            if not isinstance(layer, dict) or layer.get("resourceType") != "GMRInstanceLayer":
                continue
            for inst in layer.get("instances", []) or []:
                if not isinstance(inst, dict):
                    continue
                obj = inst.get("objectId") or {}
                if isinstance(obj, dict) and obj.get("name") == "__mcp_bridge":
                    bridge_instances.append(inst)
        self.assertEqual(len(bridge_instances), 1, msg=str(bridge_instances))


if __name__ == "__main__":
    unittest.main()

