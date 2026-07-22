#!/bin/bash
# Hook: session-start
# Triggers: When Claude Code session starts in a GameMaker workspace
# Checks for updates and reports bridge status

# Only run if this looks like a GameMaker project
if ! ls *.yyp >/dev/null 2>&1 && ! find . -maxdepth 2 -name "*.yyp" -print -quit 2>/dev/null | grep -q .; then
    exit 0
fi

echo "[gms-mcp] GameMaker project detected"

# Check for updates (only if gms-mcp is already installed locally)
if command -v gms-mcp >/dev/null 2>&1; then
    UPDATE_NOTICE=$(gms-mcp doctor --notify 2>/dev/null || echo "")
    if [ -n "$UPDATE_NOTICE" ]; then
        echo "$UPDATE_NOTICE"
    fi
fi

# Bridge state is exposed by the MCP-only gm_bridge_status tool. This shell
# hook deliberately does not claim to inspect it through a nonexistent CLI.
