"""MCP prompt discovery and rendering contract for the GameMaker prompt catalogue."""

from __future__ import annotations

import asyncio
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import Client
from mcp.server.mcpserver import MCPServer

from gms_mcp.server.prompts import PROMPT_NAMES, register


class MCPPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalogue_discovery_and_rendering_use_the_current_protocol(self):
        server = MCPServer("prompt-contract")
        register(server)

        async with Client(server, mode="2026-07-28") as client:
            listed = await client.list_prompts()
            discovered = [prompt.name for prompt in listed.prompts]
            rendered = {name: await client.get_prompt(name) for name in PROMPT_NAMES}

        self.assertEqual(discovered, list(PROMPT_NAMES))
        self.assertEqual(len(discovered), 5)
        for name, result in rendered.items():
            self.assertTrue(result.messages, name)
            text = result.messages[0].content.text
            self.assertIn("gm_", text)
            self.assertNotIn("/Users/", text)
            self.assertNotIn("password", text.lower())

        self.assertIn("Resolve", rendered["safe-refactor"].messages[0].content.text)
        self.assertIn("dry_run=true", rendered["diagnose-project"].messages[0].content.text)
        self.assertIn("parent_path", rendered["create-feature"].messages[0].content.text)
        self.assertIn("gm_compile", rendered["compile-fix-retry"].messages[0].content.text)
        self.assertIn("gm_run_status", rendered["inspect-live-game"].messages[0].content.text)

    async def test_fetching_prompts_does_not_mutate_a_project(self):
        with TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            project_file = project_root / "Game.yyp"
            project_file.write_text('{"resources":[]}', encoding="utf-8")
            before = hashlib.sha256(project_file.read_bytes()).hexdigest()

            server = MCPServer("prompt-read-only-contract")
            register(server, read_only=True)
            async with Client(server, mode="2026-07-28") as client:
                await client.list_prompts()
                for name in PROMPT_NAMES:
                    await client.get_prompt(name)

            self.assertEqual(hashlib.sha256(project_file.read_bytes()).hexdigest(), before)
            self.assertEqual(sorted(path.name for path in project_root.iterdir()), ["Game.yyp"])

    async def test_read_only_core_prompts_do_not_direct_calls_to_unavailable_mutators(self):
        server = MCPServer("prompt-profile-contract")
        register(server, enabled_toolsets=("core",), read_only=True)

        async with Client(server, mode="2026-07-28") as client:
            create = (await client.get_prompt("create-feature")).messages[0].content.text
            refactor = (await client.get_prompt("safe-refactor")).messages[0].content.text
            compile_fix = (await client.get_prompt("compile-fix-retry")).messages[0].content.text
            live = (await client.get_prompt("inspect-live-game")).messages[0].content.text

        self.assertIn("Do not attempt `gm_create_*`", create)
        self.assertIn("Rename and duplicate tools are unavailable", refactor)
        self.assertIn("bridge controls are not available", live)
        self.assertNotIn("gm_build_index", refactor)
        self.assertNotIn("gm_verification_flush", create)
        self.assertNotIn("gm_verification_flush", refactor)
        self.assertNotIn("gm_compile", compile_fix)
        self.assertIn("Do not apply a fix", compile_fix)
        self.assertNotIn("gm_run_logs", live)
        self.assertNotIn("gm_run_stop", live)
        self.assertNotIn("gm_run_status", live)


if __name__ == "__main__":
    unittest.main()
