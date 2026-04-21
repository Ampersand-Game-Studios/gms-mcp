#!/bin/zsh
set -euo pipefail

ENV_FILE="${HOME}/.config/gms-mcp/telemetry-archive.env"
REPO_ROOT="${HOME}/Projects/Ampersand Game Studios/GMS MCP/gms-mcp"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

cd "${REPO_ROOT}"
exec /opt/homebrew/bin/python3 ops/telemetry/archive/telemetry_archive.py "$@"
