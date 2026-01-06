"""Tests for Code Intelligence MCP tools integration."""

import argparse
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


class TestSymbolCommandHandlers(unittest.TestCase):
    """Tests for symbol command handlers (used by MCP tools)."""

    def setUp(self):
        """Create temporary project directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: self._cleanup_temp_dir())
        
        # Create project structure
        (Path(self.temp_dir) / "scripts").mkdir()
        (Path(self.temp_dir) / "objects").mkdir()
        
        # Create a dummy .yyp file
        (Path(self.temp_dir) / "test.yyp").write_text('{}')
        
        # Create sample GML content
        self._write_gml("scripts/player/player.gml", '''
/// @description Player initialization
/// @param initial_x Starting X position
/// @param initial_y Starting Y position
function player_init(initial_x, initial_y) {
    x = initial_x;
    y = initial_y;
}

function player_update() {
    // Update logic
    player_handle_input();
}

function player_handle_input() {
    // Input handling
}
''')
        
        self._write_gml("scripts/game/game.gml", '''
#macro GAME_VERSION "1.0.0"

enum GameState {
    MENU,
    PLAYING,
    PAUSED
}

globalvar g_game_state;

function game_start() {
    g_game_state = GameState.MENU;
    player_init(100, 200);
}
''')

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

    def test_handle_build_index(self):
        """handle_build_index should build the symbol index."""
        from gms_helpers.commands.symbol_commands import handle_build_index
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            force=True,
        )
        
        # Capture stdout
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_build_index(args)
        
        self.assertTrue(result)
        output = stdout_capture.getvalue()
        self.assertIn("[INDEX]", output)
        self.assertIn("[OK]", output)

    def test_handle_find_definition_found(self):
        """handle_find_definition should find existing symbols."""
        from gms_helpers.commands.symbol_commands import handle_find_definition
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            symbol_name="player_init",
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_find_definition(args)
        
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("found", False))
        self.assertEqual(len(result.get("definitions", [])), 1)
        self.assertEqual(result["definitions"][0]["name"], "player_init")

    def test_handle_find_definition_not_found(self):
        """handle_find_definition should handle missing symbols gracefully."""
        from gms_helpers.commands.symbol_commands import handle_find_definition
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            symbol_name="nonexistent_function",
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_find_definition(args)
        
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("found", True))
        self.assertEqual(len(result.get("definitions", [])), 0)

    def test_handle_find_references(self):
        """handle_find_references should find symbol usages."""
        from gms_helpers.commands.symbol_commands import handle_find_references
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            symbol_name="player_init",
            max_results=50,
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_find_references(args)
        
        self.assertIsInstance(result, dict)
        # player_init is called in game.gml
        self.assertTrue(result.get("found", False))
        self.assertGreater(len(result.get("references", [])), 0)

    def test_handle_list_symbols(self):
        """handle_list_symbols should list all symbols."""
        from gms_helpers.commands.symbol_commands import handle_list_symbols
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            kind=None,
            name_filter=None,
            file_filter=None,
            max_results=100,
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_list_symbols(args)
        
        self.assertIsInstance(result, dict)
        symbols = result.get("symbols", [])
        self.assertGreater(len(symbols), 0)
        
        # Should contain various symbol types
        symbol_names = {s["name"] for s in symbols}
        self.assertIn("player_init", symbol_names)
        self.assertIn("GAME_VERSION", symbol_names)
        self.assertIn("GameState", symbol_names)

    def test_handle_list_symbols_filtered_by_kind(self):
        """handle_list_symbols should filter by kind."""
        from gms_helpers.commands.symbol_commands import handle_list_symbols
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            kind="function",
            name_filter=None,
            file_filter=None,
            max_results=100,
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_list_symbols(args)
        
        symbols = result.get("symbols", [])
        # All returned symbols should be functions
        for s in symbols:
            self.assertEqual(s["kind"], "function")

    def test_handle_list_symbols_filtered_by_name(self):
        """handle_list_symbols should filter by name substring."""
        from gms_helpers.commands.symbol_commands import handle_list_symbols
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            kind=None,
            name_filter="player",
            file_filter=None,
            max_results=100,
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_list_symbols(args)
        
        symbols = result.get("symbols", [])
        # All returned symbols should contain "player" in the name
        for s in symbols:
            self.assertIn("player", s["name"].lower())


class TestCommandHandlerEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        """Create minimal temp project."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: self._cleanup_temp_dir())
        
        # Create minimal project structure
        (Path(self.temp_dir) / "scripts").mkdir()
        (Path(self.temp_dir) / "test.yyp").write_text('{}')

    def _cleanup_temp_dir(self):
        import shutil
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    def test_find_definition_missing_symbol_name(self):
        """handle_find_definition should handle missing symbol_name."""
        from gms_helpers.commands.symbol_commands import handle_find_definition
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            symbol_name=None,
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_find_definition(args)
        
        self.assertIn("error", result)

    def test_find_references_missing_symbol_name(self):
        """handle_find_references should handle missing symbol_name."""
        from gms_helpers.commands.symbol_commands import handle_find_references
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            symbol_name=None,
            max_results=50,
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_find_references(args)
        
        self.assertIn("error", result)

    def test_empty_project(self):
        """Handlers should work on projects with no GML files."""
        from gms_helpers.commands.symbol_commands import handle_list_symbols
        
        args = argparse.Namespace(
            project_root=self.temp_dir,
            kind=None,
            name_filter=None,
            file_filter=None,
            max_results=100,
        )
        
        import io
        from contextlib import redirect_stdout
        
        stdout_capture = io.StringIO()
        with redirect_stdout(stdout_capture):
            result = handle_list_symbols(args)
        
        # Should return empty list, not error
        self.assertEqual(result.get("symbols", []), [])
        self.assertEqual(result.get("count", -1), 0)


if __name__ == "__main__":
    unittest.main()
