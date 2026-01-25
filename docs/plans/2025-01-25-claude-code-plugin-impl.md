# Claude Code Plugin Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package gms-mcp as a Claude Code plugin with skills, hooks, and auto-configured MCP server.

**Architecture:** Create a `plugin/` directory at repo root containing Claude Code plugin assets. Skills move from pip package to plugin. The `gms skills` CLI commands update to reference the new location. Hooks are shell scripts triggered on session start and tool errors.

**Tech Stack:** Shell scripts (hooks), JSON (plugin manifest, mcp.json), Markdown (skills)

---

### Task 1: Create Plugin Directory Structure

**Files:**
- Create: `plugin/skills/gms-mcp/` (directory)
- Create: `plugin/hooks/` (directory)

**Step 1: Create plugin directory structure**

```bash
mkdir -p plugin/skills/gms-mcp/workflows
mkdir -p plugin/skills/gms-mcp/reference
mkdir -p plugin/hooks
```

**Step 2: Verify structure exists**

Run: `ls -la plugin/`
Expected: `skills/` and `hooks/` directories exist

**Step 3: Commit**

```bash
git add plugin/
git commit -m "chore: create plugin directory structure"
```

---

### Task 2: Move Skills to Plugin Directory

**Files:**
- Move: `src/gms_helpers/skills/gms-mcp/*` → `plugin/skills/gms-mcp/`
- Delete: `src/gms_helpers/skills/` (after move)

**Step 1: Move all skill files**

```bash
cp -r src/gms_helpers/skills/gms-mcp/* plugin/skills/gms-mcp/
```

**Step 2: Verify files moved correctly**

Run: `ls plugin/skills/gms-mcp/`
Expected: `SKILL.md`, `workflows/`, `reference/`

Run: `ls plugin/skills/gms-mcp/workflows/ | wc -l`
Expected: 18

Run: `ls plugin/skills/gms-mcp/reference/ | wc -l`
Expected: 7

**Step 3: Remove old skills directory**

```bash
rm -rf src/gms_helpers/skills/
```

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: move skills from pip package to plugin directory"
```

---

### Task 3: Update Skills Commands to Use Plugin Directory

**Files:**
- Modify: `src/gms_helpers/commands/skills_commands.py:8-10`

**Step 1: Update get_skills_source_dir function**

Change the function to look for skills in the plugin directory relative to repo root:

```python
def get_skills_source_dir() -> Path:
    """Return the path to the bundled skills directory."""
    # When installed via pip, skills are in plugin/skills relative to package
    # When running from source, skills are in plugin/skills relative to repo root

    # Try plugin directory relative to this file (for pip-installed package)
    plugin_dir = Path(__file__).parent.parent.parent.parent / "plugin" / "skills"
    if plugin_dir.exists():
        return plugin_dir

    # Fallback: try relative to current working directory (for development)
    cwd_plugin = Path.cwd() / "plugin" / "skills"
    if cwd_plugin.exists():
        return cwd_plugin

    # Final fallback: original location (backwards compatibility)
    return Path(__file__).parent.parent / "skills"
```

**Step 2: Run tests to verify skills commands still work**

Run: `python -m pytest cli/tests/python/test_skills_commands.py -v`
Expected: Tests may fail initially (expected - we need to update pyproject.toml)

**Step 3: Don't commit yet** - need to update pyproject.toml first

---

### Task 4: Update pyproject.toml Package Data

**Files:**
- Modify: `pyproject.toml` (package-data section)

**Step 1: Update package-data to exclude old skills, include plugin**

The pip package should NOT include skills anymore (they're in plugin/). But we need the plugin directory to be available when installed.

Actually, for pip package we need a different approach - pip packages can't easily include files outside the src/ directory.

**Revised approach:** Keep a copy of skills in pip package for `gms skills install` command (non-Claude users), but primary source is plugin/.

Update `pyproject.toml`:

```toml
[tool.setuptools.package-data]
gms_helpers = [
  "templates/**/*.gml",
  "test_invalid.json",
]

[tool.setuptools.data-files]
# No data-files needed - plugin is installed via Claude's /install-plugin
```

**Step 2: Create a symlink or copy mechanism for pip package**

Since pip packages need skills inside src/, we'll keep the skills in plugin/ as source of truth and update the build process.

For now, update `skills_commands.py` to check multiple locations:

```python
def get_skills_source_dir() -> Path:
    """Return the path to the bundled skills directory."""
    # Priority 1: plugin directory (when running from repo or plugin installed)
    repo_root = Path(__file__).parent.parent.parent.parent
    plugin_skills = repo_root / "plugin" / "skills"
    if plugin_skills.exists():
        return plugin_skills

    # Priority 2: installed package location
    pkg_skills = Path(__file__).parent.parent / "skills"
    if pkg_skills.exists():
        return pkg_skills

    raise FileNotFoundError("Skills directory not found")
```

**Step 3: Run tests**

Run: `python -m pytest cli/tests/python/test_skills_commands.py -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/gms_helpers/commands/skills_commands.py pyproject.toml
git commit -m "refactor: update skills source location for plugin architecture"
```

---

### Task 5: Create Plugin Manifest

**Files:**
- Create: `plugin/plugin.json`

**Step 1: Create plugin.json**

```json
{
  "name": "gms-mcp",
  "version": "0.2.0",
  "description": "GameMaker development tools for Claude Code - MCP server, skills, and hooks",
  "author": "Callum Lory",
  "repository": "github:Ampersand-Game-Studios/gms-mcp",
  "requirements": {
    "uv": true
  }
}
```

**Step 2: Verify JSON is valid**

Run: `python -c "import json; json.load(open('plugin/plugin.json'))"`
Expected: No output (valid JSON)

**Step 3: Commit**

```bash
git add plugin/plugin.json
git commit -m "feat: add Claude Code plugin manifest"
```

---

### Task 6: Create MCP Configuration

**Files:**
- Create: `plugin/mcp.json`

**Step 1: Create mcp.json with uvx configuration**

```json
{
  "mcpServers": {
    "gms-mcp": {
      "command": "uvx",
      "args": ["gms-mcp"],
      "env": {}
    }
  }
}
```

**Step 2: Verify JSON is valid**

Run: `python -c "import json; json.load(open('plugin/mcp.json'))"`
Expected: No output (valid JSON)

**Step 3: Commit**

```bash
git add plugin/mcp.json
git commit -m "feat: add MCP server configuration for Claude Code plugin"
```

---

### Task 7: Create Session Start Hook

**Files:**
- Create: `plugin/hooks/session-start.sh`

**Step 1: Create the hook script**

```bash
#!/bin/bash
# Hook: session-start
# Triggers: When Claude Code session starts in a GameMaker workspace
# Checks for updates and reports bridge status

# Only run if this looks like a GameMaker project
if ! ls *.yyp 2>/dev/null && ! find . -maxdepth 2 -name "*.yyp" -print -quit 2>/dev/null | grep -q .; then
    exit 0
fi

echo "[gms-mcp] GameMaker project detected"

# Check for updates
UPDATE_CHECK=$(uvx gms-mcp check-updates 2>/dev/null || echo "")
if echo "$UPDATE_CHECK" | grep -q "update available"; then
    echo "[gms-mcp] Update available - run: pip install --upgrade gms-mcp"
fi

# Check bridge status
BRIDGE_STATUS=$(uvx gms bridge status 2>/dev/null || echo "not installed")
if echo "$BRIDGE_STATUS" | grep -q "installed"; then
    echo "[gms-mcp] Bridge: installed"
else
    echo "[gms-mcp] Bridge: not installed (optional - for live debugging)"
fi
```

**Step 2: Make script executable**

```bash
chmod +x plugin/hooks/session-start.sh
```

**Step 3: Commit**

```bash
git add plugin/hooks/session-start.sh
git commit -m "feat: add session-start hook for update and bridge status checks"
```

---

### Task 8: Create Error Notification Hook

**Files:**
- Create: `plugin/hooks/notify-errors.sh`

**Step 1: Create the hook script**

```bash
#!/bin/bash
# Hook: notify-errors
# Triggers: After gm_run_start or gm_compile returns errors
# Parses and surfaces GameMaker compile errors in user-friendly format

# This hook receives the tool output via stdin
INPUT=$(cat)

# Check if this contains compile errors
if echo "$INPUT" | grep -qi "error\|failed"; then
    echo "[gms-mcp] Compile issues detected:"

    # Extract error lines (GameMaker format: file:line - message)
    echo "$INPUT" | grep -iE "\.gml:[0-9]+|error:|failed" | head -10 | while read -r line; do
        echo "  $line"
    done
fi
```

**Step 2: Make script executable**

```bash
chmod +x plugin/hooks/notify-errors.sh
```

**Step 3: Commit**

```bash
git add plugin/hooks/notify-errors.sh
git commit -m "feat: add error notification hook for compile failures"
```

---

### Task 9: Create Hook Configuration

**Files:**
- Create: `plugin/hooks.json`

**Step 1: Create hooks.json to register hooks with Claude Code**

```json
{
  "hooks": [
    {
      "name": "session-start",
      "event": "on_session_start",
      "script": "hooks/session-start.sh",
      "description": "Check for gms-mcp updates and bridge status"
    },
    {
      "name": "notify-errors",
      "event": "on_tool_error",
      "tools": ["gm_run_start", "gm_compile"],
      "script": "hooks/notify-errors.sh",
      "description": "Surface GameMaker compile errors"
    }
  ]
}
```

**Step 2: Verify JSON is valid**

Run: `python -c "import json; json.load(open('plugin/hooks.json'))"`
Expected: No output (valid JSON)

**Step 3: Commit**

```bash
git add plugin/hooks.json
git commit -m "feat: add hooks configuration for Claude Code plugin"
```

---

### Task 10: Update Tests for New Skills Location

**Files:**
- Modify: `cli/tests/python/test_skills_commands.py`

**Step 1: Update test to check plugin directory**

Update `TestSkillsSourceFiles.setUp`:

```python
def setUp(self):
    """Set up test environment."""
    repo_root = Path(__file__).resolve().parents[3]
    # Skills are now in plugin/ directory
    self.skills_dir = repo_root / "plugin" / "skills" / "gms-mcp"
```

**Step 2: Run tests**

Run: `python -m pytest cli/tests/python/test_skills_commands.py -v`
Expected: All 18 tests pass

**Step 3: Commit**

```bash
git add cli/tests/python/test_skills_commands.py
git commit -m "test: update skills tests for plugin directory structure"
```

---

### Task 11: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Step 1: Update README.md**

Add Claude Code plugin section:

```markdown
## Claude Code Plugin

For Claude Code users, install the plugin for the best experience:

```
/install-plugin github:Ampersand-Game-Studios/gms-mcp
```

This provides:
- **Skills**: 18 workflow guides + 7 reference docs
- **Hooks**: Automatic update checks and error notifications
- **MCP Server**: Auto-configured via uvx (no pip install needed)

### For Other Tools (Cursor, VSCode, etc.)

```bash
pip install gms-mcp
gms-mcp-init --cursor  # or --vscode, --windsurf, etc.
```
```

**Step 2: Update CHANGELOG.md**

Add under [Unreleased]:

```markdown
- **Claude Code Plugin**: Restructured as a Claude Code plugin with skills, hooks, and auto-configured MCP:
    - Install via `/install-plugin github:Ampersand-Game-Studios/gms-mcp`
    - Session-start hook checks for updates and bridge status
    - Error notification hook surfaces compile failures
    - Skills moved to plugin directory (pip package unchanged for other tools)
```

**Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: update documentation for Claude Code plugin"
```

---

### Task 12: Run Full Test Suite

**Files:** None (verification only)

**Step 1: Run complete test suite**

Run: `python -m pytest cli/tests/python/ -v --timeout=120`
Expected: All 537+ tests pass

**Step 2: Verify plugin structure**

Run: `ls -la plugin/`
Expected:
```
hooks.json
hooks/
mcp.json
plugin.json
skills/
```

Run: `ls plugin/skills/gms-mcp/`
Expected: `SKILL.md`, `reference/`, `workflows/`

**Step 3: Test skills list command**

Run: `python -m gms_helpers.gms skills list`
Expected: Lists all 26 skill files

---

### Task 13: Final Commit and Summary

**Step 1: Verify git status is clean**

Run: `git status`
Expected: Nothing to commit, working tree clean

**Step 2: Create summary commit if any loose changes**

```bash
git add -A
git commit -m "feat: complete Claude Code plugin implementation" --allow-empty
```

**Step 3: Tag release candidate**

```bash
git tag -a v0.2.0-rc1 -m "Claude Code plugin release candidate"
```
