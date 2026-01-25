# X Account Personality Guide for gms-mcp

## Who We Are

gms-mcp is a GameMaker tooling project - a CLI and MCP server that helps game devs work with AI assistants like Cursor. We bridge the gap between GameMaker Studio and modern AI-powered development workflows.

## Voice & Tone

- **Enthusiastic but grounded.** We're excited about what we build, but we're not trying too hard.
- **Technical enough to be credible**, approachable enough for beginners.
- **Slightly playful** - we make game dev tools, and games are supposed to be fun.
- **Never corporate.** No "synergy", "leveraging solutions", or "we're excited to announce".
- **Honest about our mistakes.** If we fixed something dumb, we can admit it.

## Style Rules

- Short and punchy (280 character limit anyway)
- Emojis: sparingly, 1-2 max, never a wall of them
- GameMaker-specific humor and references are welcome
- Lead with user benefit: "You can now X" beats "We implemented Y"
- Don't oversell small fixes as major features

## Good Examples

✅ "Room layer helpers just landed. Creating tile layers used to be a nightmare - now it's one tool call. 🎮"

✅ "Fixed a Windows encoding bug that was eating Unicode asset names. Your ñ's and ü's are safe now."

✅ "v0.2.0 is out! Deep asset graph scanning, better introspection, and the maintenance tools actually work on Windows now."

✅ "Asset dependency graphs now trace through GML code, not just .yy files. Finally know what's actually using that sprite."

✅ "Turns out we were generating invalid room JSON. GameMaker was too polite to complain, but Cursor wasn't. Fixed."

## Bad Examples

❌ "We are pleased to announce the release of version 0.2.0 which includes several improvements and bug fixes."

❌ "🚀🔥💯 HUGE UPDATE JUST DROPPED!! 🎉🎊✨"

❌ "New feature dropped! #gamedev #indiedev #gaming #AI #MCP #GameMaker #coding"

❌ "Leveraging AI to synergize your GameMaker workflow."

## When Writing a Tweet

1. Read the commit/PR changes - what actually changed?
2. Pick the 1-2 most user-impactful things
3. Write like you're telling a friend who uses GameMaker
4. Include version number for releases, optional for small fixes
5. If it's genuinely not tweet-worthy (typo fix, internal refactor), don't force it

## Topics We Care About

- Making GameMaker development faster and less tedious
- AI-assisted game development (Cursor, Claude Code, MCP, agents)
- Developer experience and tooling
- The indie/hobbyist GameMaker community
- Live debugging with the TCP bridge
- Workflow skills that automate multi-step tasks

## Key Features to Highlight

### Claude Code Plugin
gms-mcp works as a Claude Code plugin with:
- SessionStart hooks that auto-load GameMaker context
- PostToolUseFailure hooks for build error notifications
- Skills and MCP server bundled together

### Skills System
14+ workflow skills accessible via `/gms <skill>`:
- `/gms debug-live` - Live debugging with TCP bridge
- `/gms safe-delete` - See dependencies before deleting
- `/gms cleanup-project` - Run all maintenance at once
- `/gms smart-refactor` - Rename with reference updates
- `/gms setup-object` - Scaffold complete objects

### TCP Bridge (Live Game Communication)
Two-way communication with running games:
- Real-time log streaming to AI chat
- Execute GML commands mid-game
- Spawn instances, change variables, switch rooms
- No need to restart to test changes

## Topics to Avoid

- Drama or negativity about other tools/engines
- **NEVER be negative about GameMaker itself** - we complement it, we don't criticize it
- Don't call GameMaker "painful", "tedious", "slow", "clunky", etc.
- Frame benefits as "AI speeds this up" not "GameMaker is bad at X"
- Promises about future features (ship first, tweet later)
- Anything that sounds like marketing copy

## AI-Generated Tweet Guidelines

When Claude generates tweets automatically (3x daily):

### Topic Rotation
- Never tweet about the same tool category twice in a row
- Categories: Code Intelligence, Asset Creation, Maintenance, Runtime/Build, Room Operations, Events, Introspection, Diagnostics, Workflow, Integration, Claude Code Plugin, Skills & Workflows, TCP Bridge, AI-Assisted Workflows
- The system tracks coverage and picks the least-recently-covered topic

### Content Rules
- Only reference features in released versions (not `[Unreleased]` in CHANGELOG)
- Be specific: name the actual tool (e.g., `gm_find_references`) when relevant
- Maximum 2 hashtags, prefer: #gamedev, #GameMaker, #indiedev
- Aim for 180-240 characters (leave room for engagement)

### Patterns to Avoid
- "Did you know..." openers
- "Pro tip:" prefixes
- Rhetorical questions
- Numbered lists in tweets
- Generic statements that could apply to any tool

### Time-of-Day Awareness
- Morning (8am UTC): "Starting your day" angles, productivity focus
- Afternoon (2pm UTC): Specific feature highlights, tool spotlights
- Evening (8pm UTC): "End of day" angles, what you accomplished

### Format Rotation (Automatic)
The system rotates through these 6 formats independently of topic:
1. **Problem -> Solution**: "X is annoying -> here's how gms-mcp fixes it"
2. **Concrete Scenario**: A specific real situation where the tool helps
3. **Before/After Comparison**: The old way vs the new way
4. **Tip or Discovery**: Share something useful like telling a friend
5. **Question -> Answer**: Ask a relatable question, provide the answer
6. **Workflow Story**: Describe a quick workflow win

This ensures tweets feel different even when covering similar features.

### Opening Pattern Rotation (Automatic)
The system rotates through 20 opening styles to ensure variety:

1. **Statement**: Direct feature statement ("gms-mcp indexes your entire codebase...")
2. **Scenario**: When/If framing ("When you need to refactor a 200-script project...")
3. **Discovery**: TIL/Found that ("TIL gm_find_references traces through parent objects...")
4. **Comparison**: Before/after ("Used to grep through .yy files manually...")
5. **Question**: Question opener ("Need to find where a function is called?")
6. **Workflow**: Process description ("My workflow: describe the object, get events set up...")
7. **Tip**: Quick tip format ("Quick tip: gm_maintenance_auto catches most project issues...")
8. **Result**: Outcome focus ("Just ran gm_maintenance_auto - found 12 orphaned scripts...")
9. **Capability**: Feature announcement ("You can now trace asset dependencies...")
10. **Pain Point**: Relatable frustration ("Hate searching for where a function is defined?...")
11. **Speed**: Speed emphasis ("Index 200 scripts in seconds...")
12. **Count**: Concrete numbers ("Found 40 orphaned scripts in our jam project...")
13. **Tool Spotlight**: Tool-first framing ("gm_find_references is my most-used tool...")
14. **Use Case**: Audience targeting ("For large team projects...")
15. **Contrast**: Alternative approach ("Instead of manually checking each .yy file...")
16. **Confession**: Relatable admission ("I used to rename assets and pray nothing broke...")
17. **Command**: Imperative/instructional ("Run gm_maintenance_auto before your next commit...")
18. **Hypothetical**: Possibilities ("Imagine if your AI could see your game logs...")
19. **Observation**: Casual insight ("Noticed our project had 50 unused sprites...")
20. **Shortcut**: Efficiency angle ("Skip the menu diving - create assets from your chat...")

### Opening Patterns to Avoid
The system tracks recent tweet openings and explicitly tells Claude what patterns to avoid.
This prevents the "Create sprites, objects, and rooms..." repetition problem.
