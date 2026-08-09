#!/usr/bin/env python3
"""Test suite for skills CLI commands."""

import asyncio
import json
import re
import shlex
import unittest
import subprocess
import sys
import os
import shutil
import tarfile
import tempfile
import zipfile
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import jsonschema

from gms_helpers.gms import create_parser
from gms_helpers.transactions import validate_project_after_mutation
from gms_helpers.utils import load_json_loose
from gms_mcp.gamemaker_mcp_server import build_server
from scripts.run_mcp_tool_smoke import (
    DEFAULT_BASE_PROJECT,
    MCPToolSmokeRunner,
    create_minimal_base_project,
    should_initialize_minimal_base,
)
from scripts.verify_package_artifacts import verify_artifacts, verify_wheel


_SHELL_CONTROL_TOKENS = {"&&", "||", ";", "|", ">", ">>", "<", "<<"}


def _shell_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    segments: list[list[str]] = []
    current: list[str] = []
    for token in lexer:
        if token in _SHELL_CONTROL_TOKENS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _logical_shell_lines(block: str) -> list[str]:
    logical_lines: list[str] = []
    pending = ""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip() if pending else line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical_lines.append(pending)
        pending = ""
    if pending:
        logical_lines.append(pending)
    return logical_lines


def _documented_gms_commands(content: str) -> list[tuple[int, list[str]]]:
    commands: list[tuple[int, list[str]]] = []
    seen: set[tuple[int, tuple[str, ...]]] = set()

    for block_match in re.finditer(r"```(?:bash|sh|shell)\s*\n(.*?)```", content, flags=re.DOTALL | re.IGNORECASE):
        line_number = content.count("\n", 0, block_match.start(1)) + 1
        for offset, logical_line in enumerate(_logical_shell_lines(block_match.group(1))):
            for segment in _shell_segments(logical_line):
                if segment and segment[0] == "$":
                    segment = segment[1:]
                if not segment or segment[0] != "gms":
                    continue
                key = (line_number + offset, tuple(segment[1:]))
                if key not in seen:
                    seen.add(key)
                    commands.append((key[0], list(key[1])))

    for inline_match in re.finditer(r"`(gms\s+[^`\n]+)`", content):
        line_number = content.count("\n", 0, inline_match.start(1)) + 1
        for segment in _shell_segments(inline_match.group(1)):
            if not segment or segment[0] != "gms":
                continue
            key = (line_number, tuple(segment[1:]))
            if key not in seen:
                seen.add(key)
                commands.append((key[0], list(key[1])))
    return commands


def _documented_mcp_calls(content: str) -> list[tuple[int, str, dict[str, object]]]:
    calls: list[tuple[int, str, dict[str, object]]] = []
    for block_match in re.finditer(r"```mcp\s*\n(.*?)```", content, flags=re.DOTALL | re.IGNORECASE):
        first_line = content.count("\n", 0, block_match.start(1)) + 1
        for offset, raw_line in enumerate(block_match.group(1).splitlines()):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            tool_name, separator, raw_arguments = line.partition(" ")
            if not separator:
                raw_arguments = "{}"
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise AssertionError(f"MCP arguments must be an object at line {first_line + offset}")
            calls.append((first_line + offset, tool_name, arguments))
    return calls


class TestSkillsCommands(unittest.TestCase):
    """Test the skills CLI functionality."""

    def setUp(self):
        """Set up test environment."""
        self.python_exe = sys.executable
        repo_root = Path(__file__).resolve().parents[3]
        self.env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}
        self.repo_root = repo_root

        # Create a temporary directory for test installations
        self.temp_dir = tempfile.mkdtemp()
        self.temp_home = Path(self.temp_dir) / "home"
        self.temp_project = Path(self.temp_dir) / "project"
        self.temp_home.mkdir(parents=True)
        self.temp_project.mkdir(parents=True)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_gms_command(self, args, cwd=None):
        """Run a gms command and return result."""
        cmd = [self.python_exe, "-m", "gms_helpers.gms"] + args
        # Skills commands don't require a GameMaker project
        work_dir = cwd if cwd else self.temp_project
        result = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True, encoding="utf-8", env=self.env)
        return result.returncode, result.stdout, result.stderr

    def test_skills_help(self):
        """Test skills --help command."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("install", stdout)
        self.assertIn("list", stdout)
        self.assertIn("uninstall", stdout)

    def test_skills_install_help(self):
        """Test skills install --help command."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "install", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("--project", stdout)
        self.assertIn("--openclaw", stdout)
        self.assertIn("--force", stdout)

    def test_skills_list_help(self):
        """Test skills list --help command."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "list", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("--openclaw", stdout)
        self.assertIn("--installed", stdout)

    def test_skills_uninstall_help(self):
        """Test skills uninstall --help command."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "uninstall", "--help"])
        self.assertEqual(returncode, 0)
        self.assertIn("--project", stdout)
        self.assertIn("--openclaw", stdout)

    def test_skills_list_shows_available(self):
        """Test that skills list shows available skills."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "list"])
        self.assertEqual(returncode, 0)
        self.assertIn("Available gms-mcp skills", stdout)
        self.assertIn("SKILL.md", stdout)
        # Check for some workflow files
        self.assertIn("workflows", stdout)
        # Check for some reference files
        self.assertIn("reference", stdout)

    def test_skills_list_shows_skill_files(self):
        """Test that skills list shows the expected skill files."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "list"])
        self.assertEqual(returncode, 0)
        # Should show workflow skills
        self.assertIn("setup-object.md", stdout)
        self.assertIn("safe-delete.md", stdout)
        self.assertIn("run-game.md", stdout)
        # Should show reference files
        self.assertIn("asset-types.md", stdout)
        self.assertIn("event-types.md", stdout)

    def test_skills_install_project(self):
        """Test skills install --project works."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "install", "--project"], cwd=self.temp_project)
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("Installed", stdout)

        # Verify files were created
        skills_dir = self.temp_project / ".claude" / "skills" / "gms-mcp"
        self.assertTrue(skills_dir.exists())
        self.assertTrue((skills_dir / "SKILL.md").exists())
        self.assertTrue((skills_dir / "workflows").is_dir())
        self.assertTrue((skills_dir / "reference").is_dir())

    def test_skills_install_openclaw_project(self):
        """Test skills install --openclaw --project writes to ./skills."""
        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "install", "--openclaw", "--project"], cwd=self.temp_project
        )
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("Installed", stdout)

        skills_dir = self.temp_project / "skills" / "gms-mcp"
        self.assertTrue(skills_dir.exists())
        self.assertTrue((skills_dir / "SKILL.md").exists())
        self.assertTrue((skills_dir / "workflows").is_dir())
        self.assertTrue((skills_dir / "reference").is_dir())

    def test_skills_list_openclaw_shows_legacy_project_installs(self):
        """Test skills list --openclaw surfaces legacy workspace installs."""
        legacy_dir = self.temp_project / ".openclaw" / "skills" / "gms-mcp"
        legacy_dir.mkdir(parents=True)

        source_skill = self.repo_root / "skills" / "gms-mcp" / "SKILL.md"
        shutil.copy2(source_skill, legacy_dir / "SKILL.md")

        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "list", "--openclaw", "--installed"], cwd=self.temp_project
        )
        self.assertEqual(returncode, 0)
        self.assertIn("legacy-project", stdout)
        self.assertIn("Legacy OpenClaw workspace skills detected", stdout)

    def test_skills_install_skip_existing(self):
        """Test that install skips existing files without --force."""
        # First install
        returncode1, stdout1, stderr1 = self.run_gms_command(["skills", "install", "--project"], cwd=self.temp_project)
        self.assertEqual(returncode1, 0)

        # Second install should skip
        returncode2, stdout2, stderr2 = self.run_gms_command(["skills", "install", "--project"], cwd=self.temp_project)
        self.assertEqual(returncode2, 0)
        self.assertIn("[SKIP]", stdout2)
        self.assertIn("already exist", stdout2)

    def test_skills_install_force(self):
        """Test that install --force overwrites existing files."""
        # First install
        returncode1, stdout1, stderr1 = self.run_gms_command(["skills", "install", "--project"], cwd=self.temp_project)
        self.assertEqual(returncode1, 0)

        # Second install with --force should overwrite
        returncode2, stdout2, stderr2 = self.run_gms_command(
            ["skills", "install", "--project", "--force"], cwd=self.temp_project
        )
        self.assertEqual(returncode2, 0)
        self.assertIn("[OK]", stdout2)
        self.assertIn("Installed", stdout2)
        self.assertNotIn("[SKIP]", stdout2)

    def test_skills_uninstall_project(self):
        """Test skills uninstall --project works."""
        # First install
        self.run_gms_command(["skills", "install", "--project"], cwd=self.temp_project)

        # Verify installed
        skills_dir = self.temp_project / ".claude" / "skills" / "gms-mcp"
        self.assertTrue(skills_dir.exists())

        # Uninstall
        returncode, stdout, stderr = self.run_gms_command(["skills", "uninstall", "--project"], cwd=self.temp_project)
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("Removed", stdout)

        # Verify removed
        self.assertFalse(skills_dir.exists())

    def test_skills_uninstall_openclaw_project(self):
        """Test skills uninstall --openclaw --project works."""
        self.run_gms_command(["skills", "install", "--openclaw", "--project"], cwd=self.temp_project)

        skills_dir = self.temp_project / "skills" / "gms-mcp"
        self.assertTrue(skills_dir.exists())

        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "uninstall", "--openclaw", "--project"], cwd=self.temp_project
        )
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("Removed", stdout)
        self.assertFalse(skills_dir.exists())

    def test_skills_uninstall_openclaw_project_removes_legacy_dir(self):
        """Test uninstall removes both current and legacy OpenClaw project dirs."""
        self.run_gms_command(["skills", "install", "--openclaw", "--project"], cwd=self.temp_project)
        current_dir = self.temp_project / "skills" / "gms-mcp"
        legacy_dir = self.temp_project / ".openclaw" / "skills" / "gms-mcp"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "legacy.md").write_text("legacy", encoding="utf-8")

        self.assertTrue(current_dir.exists())
        self.assertTrue(legacy_dir.exists())

        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "uninstall", "--openclaw", "--project"], cwd=self.temp_project
        )
        self.assertEqual(returncode, 0)
        self.assertIn("both current and legacy OpenClaw workspace skill paths", stdout)
        self.assertFalse(current_dir.exists())
        self.assertFalse(legacy_dir.exists())

    def test_skills_uninstall_not_installed(self):
        """Test skills uninstall when nothing is installed."""
        returncode, stdout, stderr = self.run_gms_command(["skills", "uninstall", "--project"], cwd=self.temp_project)
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("No skills installed", stdout)


class TestSkillsSourceFiles(unittest.TestCase):
    """Test that skill source files exist and are valid."""

    def setUp(self):
        """Set up test environment."""
        repo_root = Path(__file__).resolve().parents[3]
        # Skills are at repo root (Claude Code plugin structure)
        self.skills_dir = repo_root / "skills" / "gms-mcp"

    def test_skills_source_exists(self):
        """Test that skills source directory exists."""
        self.assertTrue(self.skills_dir.exists())
        self.assertTrue(self.skills_dir.is_dir())

    def test_portable_smoke_fixture_is_valid_and_custom_paths_are_not_auto_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "fixture"
            fixture.mkdir()
            (fixture / "stale.txt").write_text("stale", encoding="utf-8")

            create_minimal_base_project(fixture)

            self.assertFalse((fixture / "stale.txt").exists())
            validation = validate_project_after_mutation(fixture)
            self.assertTrue(validation.success, msg=validation.errors)
            project = load_json_loose(fixture / "mcp_smoke.yyp")
            self.assertEqual(project["RoomOrderNodes"][0]["roomId"]["name"], "r_mcp_smoke")
            room = json.loads((fixture / "rooms" / "r_mcp_smoke" / "r_mcp_smoke.yy").read_text(encoding="utf-8"))
            self.assertEqual(room["parent"]["path"], "folders/Rooms.yy")

            self.assertTrue(should_initialize_minimal_base(DEFAULT_BASE_PROJECT, False))
            self.assertFalse(should_initialize_minimal_base(fixture, False))
            self.assertTrue(should_initialize_minimal_base(fixture, True))

    def test_smoke_preconditions_do_not_depend_on_optional_mcp_toolsets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "fixture"
            create_minimal_base_project(fixture)
            runner = MCPToolSmokeRunner(fixture, root / "work", root / "report.json")

            asyncio.run(runner._create_script(fixture, "scr_smoke_precondition"))
            asyncio.run(runner._create_object(fixture, "o_smoke_precondition"))
            asyncio.run(runner._create_room(fixture, "r_smoke_precondition"))
            asyncio.run(runner._create_sprite(fixture, "spr_smoke_precondition"))

            project = load_json_loose(fixture / "mcp_smoke.yyp")
            resources = {entry["id"]["name"]: entry["id"]["path"] for entry in project["resources"]}
            self.assertEqual(
                resources["scr_smoke_precondition"], "scripts/scr_smoke_precondition/scr_smoke_precondition.yy"
            )
            self.assertEqual(resources["o_smoke_precondition"], "objects/o_smoke_precondition/o_smoke_precondition.yy")
            self.assertEqual(resources["r_smoke_precondition"], "rooms/r_smoke_precondition/r_smoke_precondition.yy")
            self.assertEqual(
                resources["spr_smoke_precondition"],
                "sprites/spr_smoke_precondition/spr_smoke_precondition.yy",
            )

    def test_smoke_runner_starts_a_project_pinned_server_for_each_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "fixture"
            create_minimal_base_project(fixture)
            runner = MCPToolSmokeRunner(
                fixture,
                root / "work",
                root / "report.json",
                include_tools=["gm_project_info"],
            )

            with patch.dict(
                os.environ,
                {"GMS_MCP_TOOLSETS": "core", "GMS_MCP_POST_MUTATION_VERIFY": "off"},
                clear=False,
            ):
                exit_code = asyncio.run(runner.run())

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(runner.records), 1)
            self.assertTrue(runner.records[0].ok)
            self.assertEqual(runner.records[0].result["project_directory"], ".")

    def test_skill_md_exists(self):
        """Test that main SKILL.md index exists."""
        skill_md = self.skills_dir / "SKILL.md"
        self.assertTrue(skill_md.exists())

    def test_workflows_directory_exists(self):
        """Test that workflows directory exists."""
        workflows_dir = self.skills_dir / "workflows"
        self.assertTrue(workflows_dir.exists())
        self.assertTrue(workflows_dir.is_dir())

    def test_reference_directory_exists(self):
        """Test that reference directory exists."""
        reference_dir = self.skills_dir / "reference"
        self.assertTrue(reference_dir.exists())
        self.assertTrue(reference_dir.is_dir())

    def test_expected_workflow_files_exist(self):
        """Test that expected workflow files exist."""
        workflows_dir = self.skills_dir / "workflows"
        expected_workflows = [
            "setup-object.md",
            "setup-script.md",
            "setup-room.md",
            "orchestrate-macro.md",
            "smart-refactor.md",
            "duplicate-asset.md",
            "update-art.md",
            "manage-events.md",
            "safe-delete.md",
            "find-code.md",
            "lookup-docs.md",
            "analyze-logic.md",
            "generate-jsdoc.md",
            "run-game.md",
            "debug-live.md",
            "check-health.md",
            "check-quality.md",
            "cleanup-project.md",
            "pre-commit.md",
        ]
        for workflow in expected_workflows:
            workflow_file = workflows_dir / workflow
            self.assertTrue(workflow_file.exists(), f"Missing workflow file: {workflow}")

    def test_expected_reference_files_exist(self):
        """Test that expected reference files exist."""
        reference_dir = self.skills_dir / "reference"
        expected_references = [
            "asset-types.md",
            "event-types.md",
            "room-commands.md",
            "workflow-commands.md",
            "maintenance-commands.md",
            "runtime-options.md",
            "symbol-commands.md",
            "doc-commands.md",
        ]
        for ref in expected_references:
            ref_file = reference_dir / ref
            self.assertTrue(ref_file.exists(), f"Missing reference file: {ref}")

    def test_skill_files_have_frontmatter(self):
        """Test that skill files have valid YAML frontmatter."""
        for skill_file in self.skills_dir.rglob("*.md"):
            content = skill_file.read_text(encoding="utf-8")
            # Check for YAML frontmatter
            self.assertTrue(content.startswith("---"), f"Missing frontmatter in {skill_file.name}")
            # Check that frontmatter is closed
            second_delimiter = content.find("---", 3)
            self.assertGreater(second_delimiter, 3, f"Unclosed frontmatter in {skill_file.name}")
            # Check for required fields
            frontmatter = content[3:second_delimiter]
            self.assertIn("name:", frontmatter, f"Missing 'name' in {skill_file.name}")
            self.assertIn("description:", frontmatter, f"Missing 'description' in {skill_file.name}")

    def test_every_skill_example_matches_live_cli_or_mcp_schema(self):
        """Keep every agent-facing command executable as CLI and MCP schemas evolve."""
        repository_root = self.skills_dir.parents[1]
        workflows = sorted((self.skills_dir / "workflows").glob("*.md"))
        references = sorted((self.skills_dir / "reference").glob("*.md"))
        skill_docs = [self.skills_dir / "SKILL.md", *workflows, *references]
        self.assertGreater(len(workflows), 0)
        self.assertGreater(len(references), 0)

        with patch.dict(os.environ, {"GMS_MCP_TOOLSETS": "all"}, clear=False):
            mcp_tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}

        cli_parser = create_parser()
        cli_count = 0
        mcp_count = 0
        failures: list[str] = []
        per_file_contracts: dict[str, int] = {}
        for skill_doc in skill_docs:
            content = skill_doc.read_text(encoding="utf-8")
            frontmatter_match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", content, flags=re.DOTALL)
            if not frontmatter_match:
                failures.append(f"{skill_doc.name}: missing closed frontmatter")
                continue
            fields: dict[str, str] = {}
            for line in frontmatter_match.group(1).splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    fields[key.strip()] = value.strip()
            if skill_doc.parent.name == "workflows" and fields.get("name") != skill_doc.stem:
                failures.append(f"{skill_doc.name}: frontmatter name must equal {skill_doc.stem!r}")
            if not fields.get("description"):
                failures.append(f"{skill_doc.name}: frontmatter description is empty")

            file_contract_count = 0
            for line_number, arguments in _documented_gms_commands(content):
                cli_count += 1
                file_contract_count += 1
                stderr = StringIO()
                try:
                    with redirect_stderr(stderr):
                        cli_parser.parse_args(arguments)
                except SystemExit:
                    detail = stderr.getvalue().strip().splitlines()
                    failures.append(
                        f"{skill_doc.name}:{line_number}: gms {' '.join(arguments)}: "
                        f"{detail[-1] if detail else 'argument parsing failed'}"
                    )

            try:
                mcp_calls = _documented_mcp_calls(content)
            except (AssertionError, json.JSONDecodeError) as exc:
                failures.append(f"{skill_doc.name}: invalid MCP example: {exc}")
                mcp_calls = []
            for line_number, tool_name, arguments in mcp_calls:
                mcp_count += 1
                file_contract_count += 1
                tool = mcp_tools.get(tool_name)
                if tool is None:
                    failures.append(f"{skill_doc.name}:{line_number}: unknown MCP tool {tool_name!r}")
                    continue
                schema = tool.input_schema
                for error in jsonschema.Draft202012Validator(schema).iter_errors(arguments):
                    failures.append(f"{skill_doc.name}:{line_number}: {tool_name}: {error.message}")

            for block_match in re.finditer(
                r"```(?:bash|sh|shell)\s*\n(.*?)```",
                content,
                flags=re.DOTALL | re.IGNORECASE,
            ):
                for line in _logical_shell_lines(block_match.group(1)):
                    for segment in _shell_segments(line):
                        if segment and segment[0] == "python":
                            failures.append(f"{skill_doc.name}: bare python command is unsupported: {line}")

            per_file_contracts[str(skill_doc.relative_to(self.skills_dir))] = file_contract_count

        self.assertGreater(cli_count, 100)
        self.assertGreater(mcp_count, 0)
        missing_contracts = [name for name, count in per_file_contracts.items() if count == 0]
        self.assertEqual(missing_contracts, [], f"Skill files without validated examples: {missing_contracts}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_fresh_wheel_runs_skill_and_claude_bundle_setup_outside_repo(self):
        """Prove public bundle assets are present and usable in the built wheel."""
        repository_root = self.skills_dir.parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            dist_dir = temp_root / "dist"
            stale_build_file = repository_root / "build" / "lib" / "gms_mcp" / "requirements.txt"
            stale_build_file.parent.mkdir(parents=True, exist_ok=True)
            stale_build_file.write_text("stale build residue\n", encoding="utf-8")
            build_result = subprocess.run(
                [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)],
                cwd=repository_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(build_result.returncode, 0, build_result.stdout + build_result.stderr)
            wheels = list(dist_dir.glob("gms_mcp-*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as wheel_archive:
                wheel_names = set(wheel_archive.namelist())
            self.assertNotIn("gms_mcp/requirements.txt", wheel_names)
            self.assertIn("gms_helpers/bundle/skills/gms-mcp/SKILL.md", wheel_names)
            self.assertIn("gms_helpers/bundle/hooks/session-start.sh", wheel_names)
            self.assertIn("gms_helpers/bundle/hooks/hooks.json", wheel_names)

            source_archives = list(dist_dir.glob("gms_mcp-*.tar.gz"))
            self.assertEqual(len(source_archives), 1)
            verify_artifacts([*wheels, *source_archives])
            extracted_dir = temp_root / "extracted"
            with tarfile.open(source_archives[0], "r:gz") as source_archive:
                extraction_root = extracted_dir.resolve()
                for member in source_archive.getmembers():
                    self.assertTrue((extraction_root / member.name).resolve().is_relative_to(extraction_root))
                source_archive.extractall(extracted_dir)
            extracted_roots = [path for path in extracted_dir.iterdir() if path.is_dir()]
            self.assertEqual(len(extracted_roots), 1)
            sdist_wheel_dir = temp_root / "sdist-wheel"
            sdist_build_result = subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--outdir", str(sdist_wheel_dir)],
                cwd=extracted_roots[0],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(
                sdist_build_result.returncode,
                0,
                sdist_build_result.stdout + sdist_build_result.stderr,
            )
            sdist_wheels = list(sdist_wheel_dir.glob("gms_mcp-*.whl"))
            self.assertEqual(len(sdist_wheels), 1)
            verify_wheel(sdist_wheels[0])
            with zipfile.ZipFile(sdist_wheels[0]) as wheel_archive:
                sdist_wheel_names = set(wheel_archive.namelist())
            self.assertNotIn("gms_mcp/requirements.txt", sdist_wheel_names)
            self.assertIn("gms_helpers/bundle/skills/gms-mcp/SKILL.md", sdist_wheel_names)
            self.assertIn("gms_helpers/bundle/hooks/session-start.sh", sdist_wheel_names)
            self.assertIn("gms_helpers/bundle/hooks/hooks.json", sdist_wheel_names)

            venv_dir = temp_root / "venv"
            venv_result = subprocess.run(
                [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(venv_result.returncode, 0, venv_result.stdout + venv_result.stderr)
            scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
            venv_python = scripts_dir / ("python.exe" if os.name == "nt" else "python")
            install_result = subprocess.run(
                [
                    str(venv_python),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--force-reinstall",
                    str(sdist_wheels[0]),
                ],
                cwd=temp_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(install_result.returncode, 0, install_result.stdout + install_result.stderr)

            home_dir = temp_root / "home"
            workspace = temp_root / "workspace"
            home_dir.mkdir()
            workspace.mkdir()
            (workspace / "fixture.yyp").write_text("{}\n", encoding="utf-8")
            isolated_env = {
                **os.environ,
                "HOME": str(home_dir),
                "USERPROFILE": str(home_dir),
                "PYTHONPATH": "",
            }

            gms_executable = scripts_dir / ("gms.exe" if os.name == "nt" else "gms")
            list_result = subprocess.run(
                [str(gms_executable), "skills", "list"],
                cwd=workspace,
                env=isolated_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(list_result.returncode, 0, list_result.stdout + list_result.stderr)
            self.assertIn("workflows/debug-live.md", list_result.stdout)

            install_skills_result = subprocess.run(
                [str(gms_executable), "skills", "install", "--project"],
                cwd=workspace,
                env=isolated_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(
                install_skills_result.returncode,
                0,
                install_skills_result.stdout + install_skills_result.stderr,
            )
            self.assertTrue((workspace / ".claude" / "skills" / "gms-mcp" / "SKILL.md").is_file())

            init_executable = scripts_dir / ("gms-mcp-init.exe" if os.name == "nt" else "gms-mcp-init")
            plugin_result = subprocess.run(
                [
                    str(init_executable),
                    "--workspace-root",
                    str(workspace),
                    "--non-interactive",
                    "--client",
                    "claude-desktop",
                    "--scope",
                    "global",
                    "--action",
                    "setup",
                ],
                cwd=workspace,
                env=isolated_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(plugin_result.returncode, 0, plugin_result.stdout + plugin_result.stderr)
            plugin_dir = home_dir / ".claude" / "plugins" / "gms-mcp"
            self.assertTrue((plugin_dir / "hooks" / "session-start.sh").is_file())
            self.assertTrue((plugin_dir / "hooks" / "hooks.json").is_file())
            self.assertTrue((plugin_dir / "skills" / "gms-mcp" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
