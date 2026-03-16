#!/bin/bash
# Hook: session-start
# Triggers: When Claude Code session starts in a GameMaker workspace
# Checks for updates and reports bridge status

# Only run if this looks like a GameMaker project
if ! ls *.yyp 2>/dev/null && ! find . -maxdepth 2 -name "*.yyp" -print -quit 2>/dev/null | grep -q .; then
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

# Check bridge status (only if gms is already installed locally)
if command -v gms >/dev/null 2>&1; then
    BRIDGE_STATUS=$(gms bridge status 2>/dev/null || echo "not installed")
fi

if echo "${BRIDGE_STATUS:-not installed}" | grep -q "installed"; then
    echo "[gms-mcp] Bridge: installed"
else
    echo "[gms-mcp] Bridge: not installed (optional - for live debugging)"
fi
