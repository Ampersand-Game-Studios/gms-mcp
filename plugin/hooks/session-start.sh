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
