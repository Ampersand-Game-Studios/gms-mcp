import unittest
import os
import shutil
import tempfile
import sys
from pathlib import Path

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gms_helpers.asset_helper import maint_purge_command
from gms_helpers.utils import save_pretty_json_gm

class TestMaintenancePurge(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_root = Path(self.test_dir)
        
        # Create a dummy .yyp file
        self.yyp_path = self.project_root / "test_project.yyp"
        self.yyp_data = {
            "resources": [
                {"id": {"name": "obj_referenced", "path": "objects/obj_referenced/obj_referenced.yy"}}
            ]
        }
        save_pretty_json_gm(self.yyp_path, self.yyp_data)
        
        # Create directories
        (self.project_root / "objects" / "obj_referenced").mkdir(parents=True)
        (self.project_root / "objects" / "obj_orphaned").mkdir(parents=True)
        (self.project_root / "scripts").mkdir(parents=True)
        
        # Create files
        (self.project_root / "objects" / "obj_referenced" / "obj_referenced.yy").touch()
        (self.project_root / "objects" / "obj_orphaned" / "obj_orphaned.yy").touch()
        (self.project_root / "scripts" / "scr_orphaned.yy").touch()
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
    def test_purge_dry_run(self):
        class Args:
            apply = False
            delete = False
            keep = []
            project_root = self.test_dir
            
        # Should not move anything
        maint_purge_command(Args())
        
        self.assertTrue((self.project_root / "objects" / "obj_orphaned" / "obj_orphaned.yy").exists())
        self.assertTrue((self.project_root / "scripts" / "scr_orphaned.yy").exists())
        
    def test_purge_apply(self):
        class Args:
            apply = True
            delete = False
            keep = []
            project_root = self.test_dir
            
        # Should move orphaned assets to trash
        maint_purge_command(Args())
        
        self.assertFalse((self.project_root / "objects" / "obj_orphaned" / "obj_orphaned.yy").exists())
        self.assertFalse((self.project_root / "scripts" / "scr_orphaned.yy").exists())
        self.assertTrue((self.project_root / "objects" / "obj_referenced" / "obj_referenced.yy").exists())
        
        # Verify trash exists
        trash_root = self.project_root / ".maintenance_trash"
        self.assertTrue(trash_root.exists())
        
        # Verify manifest
        trash_dirs = list(trash_root.glob("trash_*"))
        self.assertEqual(len(trash_dirs), 1)
        self.assertTrue((trash_dirs[0] / "MANIFEST.txt").exists())
        
    def test_purge_with_keep_patterns(self):
        # Create keep file
        with open(self.project_root / "maintenance_keep.txt", "w") as f:
            f.write("obj_orphaned\n")
            
        class Args:
            apply = True
            delete = False
            keep = ["scr_orphaned"]
            project_root = self.test_dir
            
        # Should keep both because of patterns
        maint_purge_command(Args())
        
        self.assertTrue((self.project_root / "objects" / "obj_orphaned" / "obj_orphaned.yy").exists())
        self.assertTrue((self.project_root / "scripts" / "scr_orphaned.yy").exists())

if __name__ == "__main__":
    unittest.main()
