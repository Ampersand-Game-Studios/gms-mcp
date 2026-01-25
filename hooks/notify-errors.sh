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
