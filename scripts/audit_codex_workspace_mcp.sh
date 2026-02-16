#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Audit Codex workspace MCP coverage for GameMaker repos.

Usage:
  audit_codex_workspace_mcp.sh [--scan-root <dir>] [--server-name <name>] [--global-config <path>] [--strict]

Options:
  --scan-root <dir>       Root directory to scan for .yyp files (default: $HOME/Documents)
  --server-name <name>    MCP server name to validate in workspace configs (default: gms)
  --global-config <path>  Codex global config path (default: $HOME/.codex/config.toml)
  --strict                Treat global alias warnings as failures
  -h, --help              Show this help text
EOF
}

SCAN_ROOT="${HOME}/Documents"
SERVER_NAME="gms"
GLOBAL_CONFIG="${HOME}/.codex/config.toml"
STRICT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scan-root)
      SCAN_ROOT="${2:-}"
      shift 2
      ;;
    --server-name)
      SERVER_NAME="${2:-}"
      shift 2
      ;;
    --global-config)
      GLOBAL_CONFIG="${2:-}"
      shift 2
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! -d "$SCAN_ROOT" ]]; then
  echo "[ERROR] Scan root does not exist: $SCAN_ROOT" >&2
  exit 2
fi

find_repo_root() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.git" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

extract_gm_project_root() {
  local config_file="$1"
  local server_name="$2"

  awk -v server="$server_name" '
    $0 ~ "^\\[mcp_servers\\." server "\\]$" {
      in_server = 1
      in_env = 0
      next
    }
    $0 ~ "^\\[mcp_servers\\." server "\\.env\\]$" {
      in_server = 0
      in_env = 1
      next
    }
    $0 ~ "^\\[mcp_servers\\." {
      in_server = 0
      in_env = 0
    }
    in_env && $0 ~ /^GM_PROJECT_ROOT[[:space:]]*=/ {
      value = $0
      sub(/^[^=]*=[[:space:]]*/, "", value)
      gsub(/^"/, "", value)
      gsub(/"$/, "", value)
      print value
      exit
    }
  ' "$config_file"
}

MAP_FILE="$(mktemp -t codex-gm-map.XXXXXX)"
REPO_FILE="$(mktemp -t codex-gm-repos.XXXXXX)"
trap 'rm -f "$MAP_FILE" "$REPO_FILE"' EXIT

while IFS= read -r yyp; do
  [[ -n "$yyp" ]] || continue
  case "$yyp" in
    */prefabs/*)
      continue
      ;;
  esac

  project_dir="$(dirname "$yyp")"
  repo_root="$(find_repo_root "$project_dir" || true)"
  if [[ -z "$repo_root" ]]; then
    echo "[WARN] Skipping .yyp outside git repo: $yyp"
    continue
  fi

  printf '%s|%s|%s\n' "$repo_root" "$project_dir" "$yyp" >> "$MAP_FILE"
done < <(
  find "$SCAN_ROOT" \
    \( -name .git -o -name node_modules -o -name .venv -o -name dist -o -name build -o -name .godot \) -prune \
    -o -name '*.yyp' -print
)

if [[ ! -s "$MAP_FILE" ]]; then
  echo "[ERROR] No GameMaker .yyp files found under: $SCAN_ROOT"
  exit 1
fi

cut -d'|' -f1 "$MAP_FILE" | sort -u > "$REPO_FILE"

issues=0
warnings=0
checked=0

echo "=== Global Codex MCP Check ==="
if [[ -f "$GLOBAL_CONFIG" ]]; then
  if grep -q "^\[mcp_servers\.${SERVER_NAME}\]$" "$GLOBAL_CONFIG"; then
    echo "[FAIL] Global [$SERVER_NAME] entry present in: $GLOBAL_CONFIG"
    issues=$((issues + 1))
  else
    echo "[OK] No global [$SERVER_NAME] entry in: $GLOBAL_CONFIG"
  fi

  alias_hits="$(grep -E "^\[mcp_servers\.${SERVER_NAME}[-_]" "$GLOBAL_CONFIG" || true)"
  if [[ -n "$alias_hits" ]]; then
    echo "[WARN] Found possible project-specific aliases in global config:"
    printf '%s\n' "$alias_hits"
    warnings=$((warnings + 1))
    if [[ "$STRICT" -eq 1 ]]; then
      issues=$((issues + 1))
    fi
  else
    echo "[OK] No ${SERVER_NAME}-* global aliases detected."
  fi
else
  echo "[INFO] Global config not found at: $GLOBAL_CONFIG"
fi

echo
echo "=== Workspace Coverage Check ==="
while IFS= read -r repo; do
  [[ -n "$repo" ]] || continue
  checked=$((checked + 1))
  workspace_config="$repo/.codex/mcp.toml"
  expected_dirs="$(awk -F'|' -v r="$repo" '$1 == r { print $2 }' "$MAP_FILE" | sort -u)"

  echo "[$checked] $repo"
  if [[ ! -f "$workspace_config" ]]; then
    echo "  [FAIL] Missing workspace config: $workspace_config"
    echo "         Expected GM project dir(s):"
    while IFS= read -r expected; do
      [[ -n "$expected" ]] || continue
      echo "         - $expected"
    done <<< "$expected_dirs"
    issues=$((issues + 1))
    continue
  fi

  if ! grep -q "^\[mcp_servers\.${SERVER_NAME}\]$" "$workspace_config"; then
    echo "  [FAIL] Missing [mcp_servers.${SERVER_NAME}] in $workspace_config"
    issues=$((issues + 1))
    continue
  fi

  gm_root="$(extract_gm_project_root "$workspace_config" "$SERVER_NAME" || true)"
  if [[ -z "$gm_root" ]]; then
    echo "  [FAIL] Missing GM_PROJECT_ROOT in [mcp_servers.${SERVER_NAME}.env]"
    issues=$((issues + 1))
    continue
  fi

  if [[ ! -d "$gm_root" ]]; then
    echo "  [FAIL] GM_PROJECT_ROOT does not exist on disk: $gm_root"
    issues=$((issues + 1))
    continue
  fi

  matched="no"
  while IFS= read -r expected; do
    [[ -n "$expected" ]] || continue
    if [[ "$gm_root" == "$expected" ]]; then
      matched="yes"
      break
    fi
  done <<< "$expected_dirs"

  if [[ "$matched" == "yes" ]]; then
    echo "  [OK] GM_PROJECT_ROOT matches discovered project dir: $gm_root"
  else
    echo "  [FAIL] GM_PROJECT_ROOT does not match discovered project directories."
    echo "         Configured: $gm_root"
    echo "         Expected one of:"
    while IFS= read -r expected; do
      [[ -n "$expected" ]] || continue
      echo "         - $expected"
    done <<< "$expected_dirs"
    issues=$((issues + 1))
  fi
done < "$REPO_FILE"

echo
echo "=== Summary ==="
echo "Repos checked: $checked"
echo "Warnings: $warnings"
echo "Failures: $issues"

if [[ "$issues" -gt 0 ]]; then
  exit 1
fi

exit 0
