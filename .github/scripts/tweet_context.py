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

# Tweet formats - rotated independently of topic
# IMPORTANT: Never frame GameMaker negatively - we complement it, not criticize it
TWEET_FORMATS = {
    "problem_solution": {
        "name": "Problem -> Solution",
        "template": "Frame a common dev task -> show how gms-mcp speeds it up. Don't criticize GameMaker itself.",
        "example": "Working on a big project with 200+ scripts? `gm_find_definition` jumps to any function instantly.",
    },
    "concrete_scenario": {
        "name": "Concrete Scenario",
        "template": "Describe a specific real situation where this helps - game jams, late night debugging, big projects",
        "example": "Game jam weekend: asked Claude to scaffold player, enemies, and a test room. Had a playable prototype in 10 minutes.",
    },
    "comparison": {
        "name": "Before/After Comparison",
        "template": "Show how AI assistance speeds up the workflow. Focus on the speed gain, not criticizing the normal way.",
        "example": "Setting up 5 enemy variants with different stats used to take a while. Now I just describe them to Claude and they're ready to test.",
    },
    "tip_discovery": {
        "name": "Tip or Discovery",
        "template": "Share something useful like telling a friend - a tool capability they might not know about",
        "example": "TIL gm_get_asset_graph shows everything that references a sprite. Super useful before deleting old assets.",
    },
    "question_answer": {
        "name": "Question -> Answer",
        "template": "Ask a relatable question, provide the answer - focus on capability, not complaints",
        "example": "Want to know which scripts aren't being used anymore? gm_maintenance_list_orphans. Found 40 dead scripts in my project.",
    },
    "workflow_story": {
        "name": "Mini Workflow Story",
        "template": "Describe a quick workflow win - what you asked for, what happened",
        "example": "Asked Claude to 'duplicate rm_level1 as rm_level2 and add 3 enemy spawns'. Done in seconds. Love this workflow.",
    },
}

# Topic categories and their associated tools/features
# IMPORTANT: Each angle should be MEANINGFULLY DIFFERENT - different benefit, use case, or perspective
TOPIC_CATEGORIES = {
    "code_intelligence": {
        "name": "Code Intelligence",
        "tools": ["gm_build_index", "gm_find_definition", "gm_find_references", "gm_list_symbols"],
        "angles": [
            "Lost in a 200-script project? Find any function definition in seconds",
            "Refactoring a function? See every place it's called before you break something",
            "Onboarding to someone else's GameMaker project? Index it and explore the symbol tree",
            "Your AI assistant can actually understand your GML codebase structure now",
            "Jump from function call to definition without leaving your conversation",
            "Reviewing a PR? Index the branch and trace any function's usage",
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
            "Describe an enemy type, get a working object with events and variables set up",
            "The .yy boilerplate GameMaker generates is handled for you - correct GUIDs, paths, everything",
            "Batch-create 10 item objects with different stats from a single description",
            "Your AI can now spawn game objects that actually work in GameMaker - events, variables, sprite assignments",
            "Need a particle system object? Describe the effect, get the code and events",
            "Shader scaffolding: vertex and fragment files, object setup, one conversation",
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
            "That sprite you deleted 3 months ago? It's still referenced in 4 places. Now you can find them",
            "Project file got corrupted after a merge conflict? Lint and auto-fix it",
            "Duplicate resource entries in your .yyp silently causing issues? Dedupe them",
            "Clean up a messy inherited project - find orphans, validate JSON, fix paths",
            "Weekly maintenance: one command catches JSON errors, orphaned assets, duplicate entries",
            "Team project getting bloated? List all unreferenced scripts before your next cleanup",
        ],
    },
    "runtime_build": {
        "name": "Build & Runtime",
        "tools": ["gm_compile", "gm_run", "gm_run_stop", "gm_runtime_list", "gm_runtime_pin", "gm_runtime_verify"],
        "angles": [
            "Pin your project to a specific runtime - no more 'works on my machine' surprises",
            "CI/CD for GameMaker? Now your build server can compile without the IDE",
            "Test your game directly from your AI chat - compile, run, iterate",
            "Switching between runtime versions for different projects is actually manageable now",
            "Headless builds for your GameMaker project - perfect for automated testing",
            "List available runtimes, pick one, pin it - version management sorted",
        ],
    },
    "room_operations": {
        "name": "Room Operations",
        "tools": [
            "gm_room_layer_add", "gm_room_layer_remove", "gm_room_instance_add",
            "gm_room_ops_duplicate", "gm_room_ops_rename", "gm_room_ops_delete",
        ],
        "angles": [
            "Procedurally place 50 enemies across your level without clicking 50 times",
            "Duplicate a room template and batch-modify instances - level design at scale",
            "Room editor crashed and you need to add a layer? There's a tool for that",
            "Your AI can now understand and modify room layouts - add instances, layers, backgrounds",
            "Generate a test room with specific instance placements from a description",
            "Clone your hub room, swap the tileset layer, instant biome variant",
        ],
    },
    "events": {
        "name": "Event Management",
        "tools": ["gm_event_add", "gm_event_remove", "gm_event_duplicate", "gm_event_list", "gm_event_validate"],
        "angles": [
            "Copy your base enemy's event structure to 10 enemy variants instantly",
            "Add Draw GUI events to every UI object in your project programmatically",
            "Event files out of sync with your .yy? Validate and fix the mismatch",
            "Audit which objects have Alarm events - useful for debugging timing issues",
            "List all Step events across objects to understand your game loop",
            "Duplicate Create event logic from one object family to another",
        ],
    },
    "introspection": {
        "name": "Project Introspection",
        "tools": [
            "gm_list_assets", "gm_read_asset", "gm_search_references",
            "gm_get_asset_graph", "gm_get_project_stats", "gm_project_info",
        ],
        "angles": [
            "Before deleting that old sprite - see everything that references it first",
            "Quick project stats: how many scripts, objects, rooms? No IDE needed",
            "Search for every place a variable name appears across all your GML",
            "Asset dependency graph shows the real structure of your project",
            "Export your project structure for documentation or onboarding",
            "Find all objects using a specific parent - inheritance tree at a glance",
        ],
    },
    "diagnostics": {
        "name": "Diagnostics",
        "tools": ["gm_diagnostics", "gm_mcp_health", "gm_check_updates"],
        "angles": [
            "Environment health check: is your GameMaker setup ready to build?",
            "Something's wrong but you don't know what - run diagnostics first",
            "Verify your runtimes, licenses, and dependencies are all in order",
            "Quick sanity check before starting a long dev session",
            "New machine setup? Diagnostics tells you what's missing",
            "CI pipeline failing? Run diagnostics to check the build environment",
        ],
    },
    "workflow": {
        "name": "Workflow Tools",
        "tools": ["gm_workflow_duplicate", "gm_workflow_rename", "gm_workflow_delete"],
        "angles": [
            "Rename spr_player to spr_hero and update every reference automatically",
            "Duplicate an entire object with all its events and properties intact",
            "Safe delete: see what would break before you commit to removing an asset",
            "Refactor asset names across the project - all references update automatically",
            "Clone your player object as an NPC variant, keeping the core structure",
            "Batch rename with pattern: spr_enemy_* to spr_boss_* in one operation",
        ],
    },
    "integration": {
        "name": "AI Integration",
        "tools": [],
        "angles": [
            "Cursor, Claude Code, Windsurf - your AI editor now speaks GameMaker",
            "MCP protocol means any AI tool can understand your .yyp project",
            "Describe what you want in plain English, get valid GameMaker assets",
            "Your AI assistant finally has context about your actual project structure",
            "Pair programming with AI that understands GameMaker asset relationships",
            "Natural language to GML: describe behavior, get working code in context",
        ],
    },
    # New categories for Claude Code plugin features
    "claude_code_plugin": {
        "name": "Claude Code Plugin",
        "tools": [],
        "angles": [
            "Install gms-mcp as a Claude Code plugin - skills, hooks, and MCP server all bundled",
            "SessionStart hooks auto-load GameMaker context when you open a project",
            "PostToolUseFailure hooks notify you when builds fail",
            "One plugin.json gives Claude Code full GameMaker superpowers",
            "Plugin hooks catch build errors before they waste your time",
            "Open a .yyp folder in Claude Code, context loads automatically",
        ],
    },
    "skills_system": {
        "name": "Skills & Workflows",
        "tools": [],
        "angles": [
            "Type /gms debug-live to start live debugging - send commands to your running game",
            "/gms safe-delete shows what would break before you delete an asset",
            "/gms cleanup-project runs maintenance, finds orphans, validates JSON in one command",
            "14 workflow skills turn complex multi-step tasks into single commands",
            "/gms smart-refactor renames assets and updates every reference",
            "/gms setup-object scaffolds a complete object with events and variables",
        ],
    },
    "tcp_bridge": {
        "name": "Live Game Bridge",
        "tools": ["gm_bridge_install", "gm_bridge_status", "gm_run_command", "gm_run_logs"],
        "angles": [
            "TCP bridge lets AI see your game logs in real-time while it's running",
            "Spawn test instances mid-game: gm_run_command('instance_create_layer(...)')",
            "Debug without restarts - change variables, switch rooms, all from your editor",
            "Two-way communication: game sends logs, AI sends commands back",
            "Live log streaming: see debug output in your AI chat as it happens",
            "Test enemy spawns without recompiling - inject instances directly",
        ],
    },
    "ai_workflows": {
        "name": "AI-Assisted Workflows",
        "tools": [],
        "angles": [
            "Describe a feature, AI scaffolds the objects/scripts/rooms to build it",
            "Refactor a function and AI updates every reference across the project",
            "AI understands your actual project structure, not just generic GML",
            "From idea to playable prototype without leaving your AI chat",
            "Ask 'what uses this sprite?' - get a complete dependency analysis",
            "Code review with context: AI knows your object hierarchy and event flow",
        ],
    },
}

# Hashtags to use (will pick 1-2)
HASHTAGS = ["#gamedev", "#GameMaker", "#indiedev", "#GML", "#GameMakerStudio2"]

# Opening pattern types to encourage variety (20 options)
OPENING_PATTERNS = [
    "statement",      # Direct statement about a feature: "gms-mcp can X"
    "scenario",       # "When X happens, you can Y"
    "discovery",      # "TIL: ...", "Discovered that..."
    "comparison",     # "Used to X, now Y"
    "question",       # "Need to X? Here's how"
    "workflow",       # "My workflow: ..."
    "tip",            # "Quick tip: ..."
    "result",         # "Just X'd and Y happened" - outcome focus
    "capability",     # "You can now X" - feature announcement style
    "pain_point",     # "Hate when X? Y fixes that" - relatable frustration
    "speed",          # "X in seconds" - emphasize speed
    "count",          # "Found 40 orphaned scripts" - concrete numbers
    "tool_spotlight", # "gm_find_references is..." - tool-first framing
    "use_case",       # "For large projects..." - audience targeting
    "contrast",       # "Instead of X, just Y" - alternative approach
    "confession",     # "I used to X manually..." - relatable admission
    "command",        # "Run gm_maintenance_auto..." - imperative/instructional
    "hypothetical",   # "Imagine if your AI could..." - possibilities
    "observation",    # "Noticed that X..." - casual insight
    "shortcut",       # "Skip the menu diving..." - efficiency angle
]


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


def select_format(format_coverage: dict[str, Optional[str]]) -> str:
    """Select the least recently used tweet format."""
    # Sort by last usage time (None = never used = highest priority)
    sorted_formats = sorted(
        format_coverage.items(),
        key=lambda x: x[1] if x[1] else "1970-01-01T00:00:00Z"
    )

    # Return the least recently used format
    return sorted_formats[0][0]


def initialize_format_coverage() -> dict[str, Optional[str]]:
    """Return initial format coverage dict with all formats set to None."""
    return {fmt: None for fmt in TWEET_FORMATS.keys()}


def initialize_angle_coverage() -> dict[str, dict[str, Optional[str]]]:
    """Track when each angle within each topic was last used."""
    return {
        topic: {str(i): None for i in range(len(cat["angles"]))}
        for topic, cat in TOPIC_CATEGORIES.items()
    }


def select_angle(topic: str, angle_coverage: dict) -> tuple[int, str]:
    """Select least recently used angle for a topic."""
    topic_angles = angle_coverage.get(topic, {})
    # Default to all None if topic not in coverage
    if not topic_angles:
        topic_angles = {str(i): None for i in range(len(TOPIC_CATEGORIES[topic]["angles"]))}

    sorted_angles = sorted(
        topic_angles.items(),
        key=lambda x: x[1] if x[1] else "1970-01-01T00:00:00Z"
    )
    angle_idx = int(sorted_angles[0][0])
    return angle_idx, TOPIC_CATEGORIES[topic]["angles"][angle_idx]


def get_time_slot() -> str:
    """Get current time slot (morning/afternoon/evening) in UTC."""
    hour = datetime.now(timezone.utc).hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    else:
        return "evening"


def extract_opening_pattern(text: str) -> str:
    """Extract opening clause up to first punctuation or 8 words."""
    # Match up to first sentence-ending punctuation
    match = re.match(r'^([^.?!]+[.?!]?)', text)
    if match:
        opening = match.group(1).strip()
        words = opening.split()[:8]
        return " ".join(words)
    return " ".join(text.split()[:4])


def initialize_opening_coverage() -> dict[str, Optional[str]]:
    """Track when each opening pattern was last used."""
    return {pattern: None for pattern in OPENING_PATTERNS}


def select_opening_pattern(opening_coverage: dict) -> str:
    """Select the least recently used opening pattern."""
    # Ensure all patterns exist in coverage
    for pattern in OPENING_PATTERNS:
        if pattern not in opening_coverage:
            opening_coverage[pattern] = None

    sorted_patterns = sorted(
        opening_coverage.items(),
        key=lambda x: x[1] if x[1] else "1970-01-01T00:00:00Z"
    )
    return sorted_patterns[0][0]


def build_context_for_claude(
    topic: str,
    tweet_format: str,
    selected_angle: str,
    recent_tweets: list[dict],
    changelog_entries: list[dict],
    suggested_opening: Optional[str] = None,
) -> str:
    """Build context for Claude to generate a tweet with specific topic and format."""
    category = TOPIC_CATEGORIES.get(topic, TOPIC_CATEGORIES["integration"])
    format_info = TWEET_FORMATS.get(tweet_format, TWEET_FORMATS["problem_solution"])

    # Format recent tweets with their patterns to avoid
    recent_text = ""
    if recent_tweets:
        for t in recent_tweets[-15:]:
            preview = t.get('preview', 'No preview')
            recent_text += f"- {preview}\n"
    else:
        recent_text = "No recent tweets"

    # Extract opening patterns from recent tweets to avoid
    recent_openings = []
    for t in recent_tweets[-10:]:
        content = t.get('content') or t.get('preview', '')
        if content:
            opening = extract_opening_pattern(content)
            if opening and opening not in recent_openings:
                recent_openings.append(opening)

    openings_to_avoid = ", ".join(f'"{o}..."' for o in recent_openings) if recent_openings else "None"

    # Extract recently featured tools
    recent_tools = set()
    for t in recent_tweets[-10:]:
        recent_tools.update(t.get('tools_mentioned', []))

    tools_to_avoid = ", ".join(sorted(recent_tools)) if recent_tools else "None"

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

    # Opening pattern descriptions for guidance (20 patterns)
    opening_descriptions = {
        "statement": "Direct statement (e.g., 'gms-mcp indexes your entire codebase...')",
        "scenario": "When/If scenario (e.g., 'When you need to refactor a 200-script project...')",
        "discovery": "Discovery framing (e.g., 'TIL gm_find_references traces through parent objects...')",
        "comparison": "Before/after (e.g., 'Used to grep through .yy files manually...')",
        "question": "Question opener (e.g., 'Need to find where a function is called?')",
        "workflow": "Workflow description (e.g., 'My workflow: describe the object, get events set up...')",
        "tip": "Quick tip (e.g., 'Quick tip: gm_maintenance_auto catches most project issues...')",
        "result": "Outcome focus (e.g., 'Just ran gm_maintenance_auto - found 12 orphaned scripts...')",
        "capability": "Feature announcement (e.g., 'You can now trace asset dependencies across your whole project...')",
        "pain_point": "Relatable frustration (e.g., 'Hate searching for where a function is defined?...')",
        "speed": "Speed emphasis (e.g., 'Index 200 scripts in seconds...')",
        "count": "Concrete numbers (e.g., 'Found 40 orphaned scripts in our jam project...')",
        "tool_spotlight": "Tool-first (e.g., 'gm_find_references is my most-used tool...')",
        "use_case": "Audience targeting (e.g., 'For large team projects...')",
        "contrast": "Alternative approach (e.g., 'Instead of manually checking each .yy file...')",
        "confession": "Relatable admission (e.g., 'I used to rename assets and pray nothing broke...')",
        "command": "Imperative/instructional (e.g., 'Run gm_maintenance_auto before your next commit...')",
        "hypothetical": "Possibilities (e.g., 'Imagine if your AI could see your game logs in real-time...')",
        "observation": "Casual insight (e.g., 'Noticed our project had 50 unused sprites...')",
        "shortcut": "Efficiency angle (e.g., 'Skip the menu diving - create assets from your chat...')",
    }
    opening_guidance = opening_descriptions.get(suggested_opening, "") if suggested_opening else ""

    return f"""PROJECT: gms-mcp - GameMaker CLI and MCP server for AI-assisted game development

TOPIC: {category['name']}
Tools: {topic_tools}
Angle to explore: {selected_angle}

TWEET FORMAT TO USE: {format_info['name']}
How to write it: {format_info['template']}
Example of this format: "{format_info['example']}"

SUGGESTED OPENING STYLE: {suggested_opening or "any"}
{opening_guidance}

CRITICAL - DO NOT START WITH THESE PATTERNS (recently used):
{openings_to_avoid}

TOOLS FEATURED RECENTLY (prefer different ones):
{tools_to_avoid}

RECENT TWEETS (your tweet must feel distinctly different):
{recent_text}

RELEASED FEATURES (can reference):
{changelog_text if changelog_text else "Various GameMaker tooling improvements"}

TIME OF DAY: {get_time_slot()} UTC

HASHTAG OPTIONS (pick 1-2): {', '.join(HASHTAGS[:4])}
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
