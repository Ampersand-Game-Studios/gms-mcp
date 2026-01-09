#!/usr/bin/env python3
"""
Tweet context builder for automated X posting.

Provides:
- Changelog parsing (released features only)
- Tool catalog with categories
- Topic selection based on coverage
- Context building for Claude API
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Project root (relative to this script)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Topic categories and their associated tools/features
TOPIC_CATEGORIES = {
    "code_intelligence": {
        "name": "Code Intelligence",
        "tools": ["gm_build_index", "gm_find_definition", "gm_find_references", "gm_list_symbols"],
        "angles": [
            "Jump to any function definition instantly",
            "Find every usage of a symbol across your project",
            "Index your entire GML codebase in seconds",
            "Navigate code like a pro with symbol search",
        ],
    },
    "asset_creation": {
        "name": "Asset Creation",
        "tools": [
            "gm_create_script", "gm_create_object", "gm_create_sprite",
            "gm_create_room", "gm_create_font", "gm_create_shader",
            "gm_create_sound", "gm_create_path", "gm_create_tileset",
            "gm_create_timeline", "gm_create_sequence", "gm_create_note",
        ],
        "angles": [
            "Create any GameMaker asset with one tool call",
            "Batch create sprites, objects, rooms - no clicking",
            "Generate fully configured objects with events",
            "Stop clicking through menus to add assets",
        ],
    },
    "maintenance": {
        "name": "Project Maintenance",
        "tools": [
            "gm_maintenance_auto", "gm_maintenance_lint", "gm_maintenance_list_orphans",
            "gm_maintenance_fix_issues", "gm_maintenance_validate_json",
            "gm_maintenance_dedupe_resources", "gm_maintenance_purge",
        ],
        "angles": [
            "Clean up project mess in one command",
            "Find and fix orphaned assets automatically",
            "Lint your project structure for issues",
            "Dedupe resources and reclaim disk space",
        ],
    },
    "runtime_build": {
        "name": "Build & Runtime",
        "tools": ["gm_compile", "gm_run", "gm_run_stop", "gm_runtime_list", "gm_runtime_pin", "gm_runtime_verify"],
        "angles": [
            "Pin your runtime version - no more surprise updates",
            "Compile and run from your AI assistant",
            "List available runtimes without opening the IDE",
            "Verify your build environment is ready",
        ],
    },
    "room_operations": {
        "name": "Room Operations",
        "tools": [
            "gm_room_layer_add", "gm_room_layer_remove", "gm_room_instance_add",
            "gm_room_ops_duplicate", "gm_room_ops_rename", "gm_room_ops_delete",
        ],
        "angles": [
            "Add layers and instances programmatically",
            "Duplicate rooms with all their contents",
            "Batch room operations that used to be tedious",
            "Populate rooms without the room editor",
        ],
    },
    "events": {
        "name": "Event Management",
        "tools": ["gm_event_add", "gm_event_remove", "gm_event_duplicate", "gm_event_list", "gm_event_validate"],
        "angles": [
            "Copy events between objects instantly",
            "Add Step, Create, Draw events with code",
            "Manage object events without the IDE",
            "Validate event structure across objects",
        ],
    },
    "introspection": {
        "name": "Project Introspection",
        "tools": [
            "gm_list_assets", "gm_read_asset", "gm_search_references",
            "gm_get_asset_graph", "gm_get_project_stats", "gm_project_info",
        ],
        "angles": [
            "See every asset dependency at a glance",
            "Search references across your entire project",
            "Get project stats without opening GameMaker",
            "Trace what's using that sprite you want to delete",
        ],
    },
    "diagnostics": {
        "name": "Diagnostics",
        "tools": ["gm_diagnostics", "gm_mcp_health", "gm_check_updates"],
        "angles": [
            "One-click environment health check",
            "Verify GameMaker setup is ready to go",
            "Diagnose project issues before they bite",
            "Check for gms-mcp updates",
        ],
    },
    "workflow": {
        "name": "Workflow Tools",
        "tools": ["gm_workflow_duplicate", "gm_workflow_rename", "gm_workflow_delete"],
        "angles": [
            "Bulk rename assets across your project",
            "Duplicate entire asset hierarchies",
            "Safe delete with dependency checking",
        ],
    },
    "integration": {
        "name": "AI Integration",
        "tools": [],
        "angles": [
            "Works with Cursor, Claude Code, VS Code, and more",
            "MCP server for AI-assisted GameMaker dev",
            "Let your AI assistant understand your project",
            "Bridge GameMaker and modern AI workflows",
        ],
    },
}

# Hashtags to use (will pick 1-2)
HASHTAGS = ["#gamedev", "#GameMaker", "#indiedev", "#GML", "#GameMakerStudio2"]


def parse_changelog_released() -> list[dict]:
    """Parse CHANGELOG.md and return only released version entries."""
    changelog_path = PROJECT_ROOT / "CHANGELOG.md"
    if not changelog_path.exists():
        return []

    content = changelog_path.read_text(encoding="utf-8")
    entries = []

    # Split by version headers (## [x.x.x] or ## [Unreleased])
    version_pattern = r"^## \[(.+?)\]"
    sections = re.split(r"(?=^## \[)", content, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue

        # Extract version
        match = re.match(version_pattern, section, re.MULTILINE)
        if not match:
            continue

        version = match.group(1)

        # Skip unreleased
        if version.lower() == "unreleased":
            continue

        # Extract content (Added, Fixed, Changed sections)
        entry = {
            "version": version,
            "added": [],
            "fixed": [],
            "changed": [],
        }

        # Parse each subsection
        for subsection in ["Added", "Fixed", "Changed"]:
            pattern = rf"### {subsection}\n(.*?)(?=###|\Z)"
            sub_match = re.search(pattern, section, re.DOTALL)
            if sub_match:
                items = re.findall(r"^- \*\*(.+?)\*\*:?\s*(.+?)(?=\n-|\Z)", sub_match.group(1), re.MULTILINE | re.DOTALL)
                entry[subsection.lower()] = [{"title": t.strip(), "desc": d.strip()[:200]} for t, d in items]

        entries.append(entry)

    return entries[:3]  # Return last 3 versions


def get_readme_summary() -> str:
    """Get a brief summary from README.md."""
    readme_path = PROJECT_ROOT / "README.md"
    if not readme_path.exists():
        return "gms-mcp: GameMaker CLI and MCP server for AI-assisted development."

    content = readme_path.read_text(encoding="utf-8")

    # Try to extract the first paragraph after the title
    lines = content.split("\n")
    summary_lines = []
    in_summary = False

    for line in lines:
        if line.startswith("# "):
            in_summary = True
            continue
        if in_summary:
            if line.strip() == "":
                if summary_lines:
                    break
                continue
            if line.startswith("#") or line.startswith("```"):
                break
            summary_lines.append(line.strip())

    summary = " ".join(summary_lines)[:500]
    return summary if summary else "gms-mcp: GameMaker CLI and MCP server for AI-assisted development."


def select_topic(topic_coverage: dict[str, Optional[str]]) -> str:
    """Select the least recently covered topic."""
    # Sort by last coverage time (None = never covered = highest priority)
    sorted_topics = sorted(
        topic_coverage.items(),
        key=lambda x: x[1] if x[1] else "1970-01-01T00:00:00Z"
    )

    # Return the least recently covered topic
    return sorted_topics[0][0]


def get_time_slot() -> str:
    """Get current time slot (morning/afternoon/evening) in UTC."""
    hour = datetime.now(timezone.utc).hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    else:
        return "evening"


def build_context_for_claude(
    topic: str,
    recent_tweets: list[dict],
    changelog_entries: list[dict],
) -> str:
    """Build minimal context for Claude to generate a tweet."""
    category = TOPIC_CATEGORIES.get(topic, TOPIC_CATEGORIES["integration"])

    # Format recent tweets
    recent_text = "\n".join(
        f"- {t.get('preview', 'No preview')}" for t in recent_tweets[-10:]
    ) if recent_tweets else "No recent tweets"

    # Format changelog highlights
    changelog_text = ""
    for entry in changelog_entries[:2]:
        version = entry["version"]
        highlights = entry.get("added", [])[:3]
        if highlights:
            items = "\n".join(f"  - {h['title']}" for h in highlights)
            changelog_text += f"Version {version}:\n{items}\n"

    # Format topic details
    topic_tools = ", ".join(category["tools"][:5]) if category["tools"] else "General features"
    topic_angles = "\n".join(f"  - {a}" for a in category["angles"][:3])

    return f"""PROJECT: gms-mcp - GameMaker CLI and MCP server for AI-assisted game development

TOPIC TO FOCUS ON: {category['name']}
Tools in this category: {topic_tools}
Suggested angles:
{topic_angles}

RECENT TWEETS (avoid similar content):
{recent_text}

RELEASED FEATURES (can reference):
{changelog_text if changelog_text else "Various GameMaker tooling improvements"}

TIME OF DAY: {get_time_slot()} UTC

HASHTAG OPTIONS: {', '.join(HASHTAGS[:3])}
"""


def get_personality_guide() -> str:
    """Load the X personality guide."""
    guide_path = PROJECT_ROOT / ".github" / "x-personality.md"
    if guide_path.exists():
        return guide_path.read_text(encoding="utf-8")
    return """
Voice: Enthusiastic but grounded, technical but approachable, slightly playful.
Style: Short and punchy, 1-2 emojis max, lead with user benefit.
Avoid: Corporate speak, spam hashtags, overpromising.
"""


def initialize_topic_coverage() -> dict[str, Optional[str]]:
    """Return initial topic coverage dict with all topics set to None."""
    return {topic: None for topic in TOPIC_CATEGORIES.keys()}
