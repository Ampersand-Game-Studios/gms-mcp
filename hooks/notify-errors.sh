#!/bin/bash
# Hook: notify-errors
# Triggers: After the packaged gm_run or gm_compile MCP tool fails
# Surfaces compact GameMaker failure context without external dependencies

# This hook receives the tool output via stdin
INPUT=$(cat)

# PostToolUse can carry a structured domain failure without a hook-level failure.
# PostToolUseFailure always represents a failed tool invocation.
if printf '%s\n' "$INPUT" | grep -Eq \
    '"hook_event_name"[[:space:]]*:[[:space:]]*"PostToolUseFailure"|"(ok|success)"[[:space:]]*:[[:space:]]*false|"error"[[:space:]]*:[[:space:]]*"[^"]+'; then
    echo "[gms-mcp] Compile issues detected:"

    # Extract compact error-bearing fragments from the JSON hook input.
    printf '%s\n' "$INPUT" | grep -ioE '.{0,100}(\.gml:[0-9]+|error|failed).{0,180}' | head -10 | while read -r line; do
        echo "  $line"
    done
fi
