#!/usr/bin/env python3
"""Test suite for skills CLI commands."""

import unittest
import subprocess
import sys
import os
import shutil
import tempfile
from pathlib import Path


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
        result = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            encoding='utf-8',
            env=self.env
        )
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
        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "install", "--project"],
            cwd=self.temp_project
        )
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
        """Test skills install --openclaw --project writes to .openclaw."""
        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "install", "--openclaw", "--project"],
            cwd=self.temp_project
        )
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("Installed", stdout)

        skills_dir = self.temp_project / ".openclaw" / "skills" / "gms-mcp"
        self.assertTrue(skills_dir.exists())
        self.assertTrue((skills_dir / "SKILL.md").exists())
        self.assertTrue((skills_dir / "workflows").is_dir())
        self.assertTrue((skills_dir / "reference").is_dir())

    def test_skills_install_skip_existing(self):
        """Test that install skips existing files without --force."""
        # First install
        returncode1, stdout1, stderr1 = self.run_gms_command(
            ["skills", "install", "--project"],
            cwd=self.temp_project
        )
        self.assertEqual(returncode1, 0)

        # Second install should skip
        returncode2, stdout2, stderr2 = self.run_gms_command(
            ["skills", "install", "--project"],
            cwd=self.temp_project
        )
        self.assertEqual(returncode2, 0)
        self.assertIn("[SKIP]", stdout2)
        self.assertIn("already exist", stdout2)

    def test_skills_install_force(self):
        """Test that install --force overwrites existing files."""
        # First install
        returncode1, stdout1, stderr1 = self.run_gms_command(
            ["skills", "install", "--project"],
            cwd=self.temp_project
        )
        self.assertEqual(returncode1, 0)

        # Second install with --force should overwrite
        returncode2, stdout2, stderr2 = self.run_gms_command(
            ["skills", "install", "--project", "--force"],
            cwd=self.temp_project
        )
        self.assertEqual(returncode2, 0)
        self.assertIn("[OK]", stdout2)
        self.assertIn("Installed", stdout2)
        self.assertNotIn("[SKIP]", stdout2)

    def test_skills_uninstall_project(self):
        """Test skills uninstall --project works."""
        # First install
        self.run_gms_command(
            ["skills", "install", "--project"],
            cwd=self.temp_project
        )

        # Verify installed
        skills_dir = self.temp_project / ".claude" / "skills" / "gms-mcp"
        self.assertTrue(skills_dir.exists())

        # Uninstall
        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "uninstall", "--project"],
            cwd=self.temp_project
        )
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("Removed", stdout)

        # Verify removed
        self.assertFalse(skills_dir.exists())

    def test_skills_uninstall_openclaw_project(self):
        """Test skills uninstall --openclaw --project works."""
        self.run_gms_command(
            ["skills", "install", "--openclaw", "--project"],
            cwd=self.temp_project
        )

        skills_dir = self.temp_project / ".openclaw" / "skills" / "gms-mcp"
        self.assertTrue(skills_dir.exists())

        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "uninstall", "--openclaw", "--project"],
            cwd=self.temp_project
        )
        self.assertEqual(returncode, 0)
        self.assertIn("[OK]", stdout)
        self.assertIn("Removed", stdout)
        self.assertFalse(skills_dir.exists())

    def test_skills_uninstall_not_installed(self):
        """Test skills uninstall when nothing is installed."""
        returncode, stdout, stderr = self.run_gms_command(
            ["skills", "uninstall", "--project"],
            cwd=self.temp_project
        )
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
            "pre-commit.md"
        ]
        for workflow in expected_workflows:
            workflow_file = workflows_dir / workflow
            self.assertTrue(
                workflow_file.exists(),
                f"Missing workflow file: {workflow}"
            )

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
            "doc-commands.md"
        ]
        for ref in expected_references:
            ref_file = reference_dir / ref
            self.assertTrue(
                ref_file.exists(),
                f"Missing reference file: {ref}"
            )

    def test_skill_files_have_frontmatter(self):
        """Test that skill files have valid YAML frontmatter."""
        for skill_file in self.skills_dir.rglob("*.md"):
            content = skill_file.read_text(encoding='utf-8')
            # Check for YAML frontmatter
            self.assertTrue(
                content.startswith("---"),
                f"Missing frontmatter in {skill_file.name}"
            )
            # Check that frontmatter is closed
            second_delimiter = content.find("---", 3)
            self.assertGreater(
                second_delimiter, 3,
                f"Unclosed frontmatter in {skill_file.name}"
            )
            # Check for required fields
            frontmatter = content[3:second_delimiter]
            self.assertIn("name:", frontmatter, f"Missing 'name' in {skill_file.name}")
            self.assertIn("description:", frontmatter, f"Missing 'description' in {skill_file.name}")


if __name__ == "__main__":
    unittest.main()
