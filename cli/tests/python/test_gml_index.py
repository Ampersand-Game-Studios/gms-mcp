"""Tests for GML Symbol Indexing Engine."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure correct imports
SCRIPT_DIR = Path(__file__).resolve().parent
CLI_DIR = SCRIPT_DIR.parent.parent
REPO_ROOT = CLI_DIR.parent

if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


class TestGMLScanner(unittest.TestCase):
    """Tests for the GML file scanner."""

    def setUp(self):
        """Create temporary directory with test GML files."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: self._cleanup_temp_dir())
        
    def _cleanup_temp_dir(self):
        """Clean up temp directory."""
        import shutil
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    def _write_gml(self, filename: str, content: str) -> Path:
        """Write a GML file to temp directory."""
        path = Path(self.temp_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def test_scan_function_definitions(self):
        """Scanner should find function definitions."""
        from gms_helpers.gml_index import GMLScanner
        
        gml_content = '''
/// @description Test function
/// @param arg1 First argument
function my_test_function(arg1, arg2) {
    return arg1 + arg2;
}

function another_function() {
    // no args
}
'''
        path = self._write_gml("scripts/test.gml", gml_content)
        
        scanner = GMLScanner()
        symbols, refs = scanner.scan_file(path)
        
        # Should find 2 functions
        functions = [s for s in symbols if s.kind.value == "function"]
        self.assertEqual(len(functions), 2)
        
        # Check first function details
        my_func = next((f for f in functions if f.name == "my_test_function"), None)
        self.assertIsNotNone(my_func)
        self.assertEqual(my_func.parameters, ["arg1", "arg2"])

    def test_scan_constructor(self):
        """Scanner should find constructor functions."""
        from gms_helpers.gml_index import GMLScanner
        
        gml_content = '''
function Vector2(x, y) constructor {
    self.x = x;
    self.y = y;
}
'''
        path = self._write_gml("scripts/vec.gml", gml_content)
        
        scanner = GMLScanner()
        symbols, refs = scanner.scan_file(path)
        
        constructors = [s for s in symbols if s.kind.value == "constructor"]
        self.assertEqual(len(constructors), 1)
        self.assertEqual(constructors[0].name, "Vector2")

    def test_scan_enum(self):
        """Scanner should find enum definitions and values."""
        from gms_helpers.gml_index import GMLScanner
        
        gml_content = '''
enum Colors {
    RED,
    GREEN,
    BLUE
}
'''
        path = self._write_gml("scripts/enums.gml", gml_content)
        
        scanner = GMLScanner()
        symbols, refs = scanner.scan_file(path)
        
        # Should find 1 enum and 3 enum values
        enums = [s for s in symbols if s.kind.value == "enum"]
        enum_values = [s for s in symbols if s.kind.value == "enum_value"]
        
        self.assertEqual(len(enums), 1)
        self.assertEqual(enums[0].name, "Colors")
        
        self.assertEqual(len(enum_values), 3)
        value_names = {v.name for v in enum_values}
        self.assertEqual(value_names, {"RED", "GREEN", "BLUE"})
        
        # Check parent_enum is set
        for v in enum_values:
            self.assertEqual(v.parent_enum, "Colors")

    def test_scan_macro(self):
        """Scanner should find macro definitions."""
        from gms_helpers.gml_index import GMLScanner
        
        gml_content = '''
#macro GAME_WIDTH 1920
#macro GAME_HEIGHT 1080
#macro DEBUG_MODE true
'''
        path = self._write_gml("scripts/macros.gml", gml_content)
        
        scanner = GMLScanner()
        symbols, refs = scanner.scan_file(path)
        
        macros = [s for s in symbols if s.kind.value == "macro"]
        self.assertEqual(len(macros), 3)
        
        macro_names = {m.name for m in macros}
        self.assertEqual(macro_names, {"GAME_WIDTH", "GAME_HEIGHT", "DEBUG_MODE"})

    def test_scan_globalvar(self):
        """Scanner should find globalvar declarations."""
        from gms_helpers.gml_index import GMLScanner
        
        gml_content = '''
globalvar g_player;
globalvar g_score;
'''
        path = self._write_gml("scripts/globals.gml", gml_content)
        
        scanner = GMLScanner()
        symbols, refs = scanner.scan_file(path)
        
        globalvars = [s for s in symbols if s.kind.value == "globalvar"]
        self.assertEqual(len(globalvars), 2)
        
        gvar_names = {g.name for g in globalvars}
        self.assertEqual(gvar_names, {"g_player", "g_score"})

    def test_scan_references(self):
        """Scanner should find symbol references."""
        from gms_helpers.gml_index import GMLScanner
        
        gml_content = '''
function setup() {
    my_helper();
    var result = calculate_something(10);
}
'''
        path = self._write_gml("scripts/refs.gml", gml_content)
        
        scanner = GMLScanner()
        symbols, refs = scanner.scan_file(path)
        
        # Should have references to my_helper and calculate_something
        ref_names = {r.symbol_name for r in refs}
        self.assertIn("my_helper", ref_names)
        self.assertIn("calculate_something", ref_names)


class TestGMLIndex(unittest.TestCase):
    """Tests for the GML Index manager."""

    def setUp(self):
        """Create temporary project directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: self._cleanup_temp_dir())
        
        # Create project structure
        (Path(self.temp_dir) / "scripts").mkdir()
        (Path(self.temp_dir) / "objects").mkdir()
        
        # Create a dummy .yyp file
        (Path(self.temp_dir) / "test.yyp").write_text('{}')
        
    def _cleanup_temp_dir(self):
        """Clean up temp directory."""
        import shutil
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    def _write_gml(self, rel_path: str, content: str) -> Path:
        """Write a GML file to temp project."""
        path = Path(self.temp_dir) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def test_build_index(self):
        """Index should build successfully from GML files."""
        from gms_helpers.gml_index import GMLIndex
        
        # Create some GML files
        self._write_gml("scripts/utils/utils.gml", '''
function helper_function(x) {
    return x * 2;
}
''')
        self._write_gml("scripts/game/game.gml", '''
function game_start() {
    helper_function(10);
}
''')
        
        index = GMLIndex(Path(self.temp_dir))
        stats = index.build(force=True)
        
        self.assertIn("status", stats)
        self.assertEqual(stats["status"], "built")
        self.assertGreater(stats["symbols"], 0)
        self.assertGreater(stats["files"], 0)

    def test_find_definition(self):
        """Index should find symbol definitions."""
        from gms_helpers.gml_index import GMLIndex
        
        self._write_gml("scripts/funcs.gml", '''
function my_unique_function() {
    return 42;
}
''')
        
        index = GMLIndex(Path(self.temp_dir))
        index.build(force=True)
        
        defs = index.find_definition("my_unique_function")
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0].name, "my_unique_function")
        self.assertEqual(defs[0].kind.value, "function")

    def test_find_definition_not_found(self):
        """Index should return empty list for non-existent symbols."""
        from gms_helpers.gml_index import GMLIndex
        
        self._write_gml("scripts/empty.gml", '// empty')
        
        index = GMLIndex(Path(self.temp_dir))
        index.build(force=True)
        
        defs = index.find_definition("nonexistent_symbol")
        self.assertEqual(len(defs), 0)

    def test_find_references(self):
        """Index should find symbol references."""
        from gms_helpers.gml_index import GMLIndex
        
        self._write_gml("scripts/defs.gml", '''
function target_func() {
    return 1;
}
''')
        self._write_gml("scripts/usage.gml", '''
function caller() {
    target_func();
    var x = target_func();
}
''')
        
        index = GMLIndex(Path(self.temp_dir))
        index.build(force=True)
        
        refs = index.find_references("target_func")
        # Should find at least 2 references (the calls in usage.gml)
        self.assertGreaterEqual(len(refs), 2)

    def test_list_symbols_filtered_by_kind(self):
        """Index should filter symbols by kind."""
        from gms_helpers.gml_index import GMLIndex, SymbolKind
        
        self._write_gml("scripts/mixed.gml", '''
function my_func() {}
#macro MY_MACRO 1
enum MyEnum { VALUE }
globalvar g_test;
''')
        
        index = GMLIndex(Path(self.temp_dir))
        index.build(force=True)
        
        # Filter by function
        funcs = index.list_symbols(kind=SymbolKind.FUNCTION)
        func_names = {s.name for s in funcs}
        self.assertIn("my_func", func_names)
        
        # Filter by macro
        macros = index.list_symbols(kind=SymbolKind.MACRO)
        macro_names = {s.name for s in macros}
        self.assertIn("MY_MACRO", macro_names)

    def test_list_symbols_filtered_by_name(self):
        """Index should filter symbols by name substring."""
        from gms_helpers.gml_index import GMLIndex
        
        self._write_gml("scripts/named.gml", '''
function player_init() {}
function player_update() {}
function enemy_init() {}
''')
        
        index = GMLIndex(Path(self.temp_dir))
        index.build(force=True)
        
        # Filter by "player"
        player_syms = index.list_symbols(name_filter="player")
        names = {s.name for s in player_syms}
        
        self.assertIn("player_init", names)
        self.assertIn("player_update", names)
        self.assertNotIn("enemy_init", names)

    def test_cache_persistence(self):
        """Index should use cache on subsequent builds."""
        from gms_helpers.gml_index import GMLIndex
        
        self._write_gml("scripts/cached.gml", '''
function cached_func() {}
''')
        
        index = GMLIndex(Path(self.temp_dir))
        
        # First build - should build fresh
        stats1 = index.build(force=True)
        self.assertEqual(stats1["status"], "built")
        
        # Second build - should use cache
        index2 = GMLIndex(Path(self.temp_dir))
        stats2 = index2.build(force=False)
        self.assertEqual(stats2["status"], "cached")


class TestSymbolDataclasses(unittest.TestCase):
    """Tests for symbol dataclasses."""

    def test_symbol_to_dict(self):
        """Symbol.to_dict() should produce JSON-serializable output."""
        from gms_helpers.gml_index import Symbol, SymbolKind, SymbolLocation
        
        symbol = Symbol(
            name="test_func",
            kind=SymbolKind.FUNCTION,
            location=SymbolLocation(
                file_path=Path("/project/scripts/test.gml"),
                line=10,
                column=0,
            ),
            doc_comment="A test function",
            parameters=["arg1", "arg2"],
        )
        
        d = symbol.to_dict()
        
        self.assertEqual(d["name"], "test_func")
        self.assertEqual(d["kind"], "function")
        self.assertEqual(d["location"]["line"], 10)
        self.assertEqual(d["doc"], "A test function")
        self.assertEqual(d["parameters"], ["arg1", "arg2"])

    def test_symbol_reference_to_dict(self):
        """SymbolReference.to_dict() should produce JSON-serializable output."""
        from gms_helpers.gml_index import SymbolReference, SymbolLocation
        
        ref = SymbolReference(
            symbol_name="my_func",
            location=SymbolLocation(
                file_path=Path("/project/scripts/caller.gml"),
                line=25,
                column=4,
            ),
            context="    my_func();",
        )
        
        d = ref.to_dict()
        
        self.assertEqual(d["symbol"], "my_func")
        self.assertEqual(d["location"]["line"], 25)
        self.assertEqual(d["context"], "    my_func();")


if __name__ == "__main__":
    unittest.main()
