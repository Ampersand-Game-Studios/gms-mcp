# GameMaker MCP Tools
[![CI](https://github.com/Ampersand-Game-Studios/gms-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Ampersand-Game-Studios/gms-mcp/actions/workflows/ci.yml)
[![GitHub stars](https://img.shields.io/github/stars/Ampersand-Game-Studios/gms-mcp?label=GitHub%20stars)](https://github.com/Ampersand-Game-Studios/gms-mcp/stargazers)

## Project Features

- `gms`: a Python CLI for GameMaker project operations (asset creation, maintenance, runner, etc).
- `gms-mcp`: an MCP server that exposes the same operations as MCP tools (Cursor is the primary example client).
- **TCP Bridge (optional)**: live, bidirectional game communication (commands + log capture) via `gm_bridge_install`, `gm_run_command`, and `gm_run_logs`. Bridge lifecycle logging stays off the MCP stdio transport so `gm_run(..., enable_bridge=true)` does not corrupt JSON-RPC. See `documentation/BRIDGE.md`.
- **Reliability-First Architecture**: Custom exception hierarchy, typed result objects, and an execution policy manager replace monolithic exit calls and raw dictionaries. Legacy helper results are normalized into structured `success`/`ok`/`message`/`error` payloads for consistent tool integration and optimized performance (Fast assets, Resilient runner).
- **Health & Diagnostics**: `gm_mcp_health` provides a one-click diagnostic tool to verify the local GameMaker environment. `gm_diagnostics` provides structured, machine-readable project diagnostics (JSON, naming, orphans, references) compatible with IDE problem panels.
- **Imported Template Cleanup**: `gms maintenance normalize-names` / `gm_maintenance_normalize_names` plans naming-convention renames, and applies them only when explicitly requested.
- **Runtime Management**: `gm_runtime_list`, `gm_runtime_pin`, and `gm_runtime_verify` allow precise control over builds and execution. Unpinned projects prefer the runtime family recorded by their IDE version, then the newest stable runtime; LTS2026 installs are identified as LTS.
- **Cross-Platform Runner Defaults**: `gm_run` / `gm_compile` now default to the host OS target platform (`macOS`, `Linux`, or `Windows`) when not explicitly provided.
- **macOS Local Runner Behavior**: local `gm_run` / `gm_compile` use Igor's run-based path for IDE-equivalent validation without Developer ID packaging. Launches wait for existing IDE or MCP Igor activity, snapshot all runner PIDs, and attach a unique inherited ownership marker so cleanup can distinguish owned path-bearing and bare Download runners from user processes. Packaged temp-output runs still resolve `.app` bundles via `Contents/MacOS/` when `PackageZip` is used.
- **GML Symbol Indexing & Code Intelligence**: `gm_build_index`, `gm_find_definition`, `gm_find_references`, and `gm_list_symbols` provide deep, fast, and filtered code analysis (definitions and cross-file references).
- **Introspection**: complete project inspection with support for all asset types (including extensions and datafiles).
- **MCP Resources**: addressable project index and asset graph for high-performance agent context loading.
- **MCP 2.0 Runtime Features**: modern clients receive cache hints, structured tool failures, live project-resource updates after committed mutations or external project edits, safe RFC6570 asset/room resource templates, and multi-round Resolve input requests for exceptional mutation choices.
- **Resolve Safety Policies**: normal calls remain automatic. Dependency-blocked asset/room deletion can request an explicit force-or-cancel choice; name collisions request a replacement name and never overwrite; referenced texture-group deletion requests a valid reassignment. Every resumed operation reauthorizes and revalidates immediately before writing.
- **MCP Apps Dashboard**: clients that support MCP Apps can render a read-only project dashboard; every client still receives the same useful text and structured dashboard result.
- **Local Streamable HTTP**: `gms-mcp server --transport streamable-http --host 127.0.0.1` provides stateless MCP HTTP for local clients. It rejects non-loopback binds and unapproved Host/Origin headers, and supports validated `Mcp-Param-*` routing headers; it is not a remote shared-server deployment mode.
- `gms-mcp-init`: generates shareable MCP config files for a workspace. Now auto-detects environment variables like `GMS_MCP_GMS_PATH` to include in the generated config.
- **Privacy-Safe Telemetry (opt-in)**: `gms`, `gms-mcp-init`, and MCP usage can send anonymous usage metadata only after explicit consent.

The MCP server starts with a curated core toolset. Enable optional domains with `GMS_MCP_TOOLSETS=assets,events,rooms` or use `GMS_MCP_TOOLSETS=all`; `gm_capabilities` reports the active profile and available domains.

MCP SDK OpenTelemetry middleware is active by default. It creates spans only when the host configures an OpenTelemetry exporter; GMS MCP does not send telemetry to an external tracing service by itself.

## Install (recommended: pipx)

```bash
pipx install gms-mcp
```

If `gms-mcp` is useful, consider starring the repo on GitHub. Stars help other GameMaker users find it.

PowerShell equivalent:

```powershell
pipx install gms-mcp
```

## Claude Code Plugin

For Claude Code users, install the plugin for the best experience:

```
/install-plugin github:Ampersand-Game-Studios/gms-mcp
```

This provides:
- **Skills**: 19 workflow guides + 8 reference docs
- **Hooks**: Once-daily update reminders and error notifications
- **MCP Server**: Auto-configured via uvx (no pip install needed)

### For Other Tools (Cursor, VSCode, OpenClaw, etc.)

```bash
pip install gms-mcp
gms-mcp doctor            # quick package + project-detection + update check
gms-mcp doctor --project  # project-aware environment check
gms-mcp doctor --full     # add runtime selection + bridge status
gms-mcp-init --cursor     # or --vscode, --windsurf, --openclaw, etc.
```

For skill packs, OpenClaw users can install to user or workspace scope:

```bash
gms skills install --openclaw            # user scope: ~/.openclaw/skills/
gms skills install --openclaw --project  # workspace scope: ./skills/
```

Note: `.openclaw/openclaw.json` is for settings. Workspace skills are loaded from `./skills/`.

### For Codex

```bash
gms-mcp-init --codex
```

This writes a workspace `.codex/mcp.toml` file and prints the `codex mcp add` registration command.

Global config mode writes directly to `~/.codex/config.toml` (merging server entries).

Use the printed command directly, or copy `.codex/mcp.toml` content into the `[mcp_servers]` section of your `~/.codex/config.toml`.

Codex helpers:
- `gms-mcp-init --codex-check` prints detected Codex config paths and active server entry, with secret-like values redacted.
- `gms-mcp-init --codex-check-json` prints the same check output in machine-readable JSON, with secret-like values redacted.
- `gms-mcp-init --codex-dry-run-only` prints final merged payloads for workspace + global Codex config without writing files.
- `gms-mcp-init --codex-app-setup` runs one-shot Codex app setup: writes workspace config, previews global merge, then prints check + readiness summary.

## Telemetry

Telemetry is `default off`.

- Consent is user-scoped in `~/.gms-mcp/telemetry.json`
- Interactive `gms` and `gms-mcp-init` runs can prompt once for consent
- MCP server startup never prompts on stdio
- By default telemetry excludes file paths, command arguments, stdout/stderr, project names, usernames, emails, hostnames, and persistent IDs

CLI controls:

```bash
gms telemetry status
gms telemetry enable
gms telemetry enable --with-install-id
gms telemetry disable
gms telemetry flush
gms telemetry clear
```

Runtime overrides:

```bash
gms --telemetry=off maintenance auto
gms-mcp-init --telemetry=on --cursor
GMS_MCP_TELEMETRY=off gms asset create script my_script
```

## Imported Template Cleanup

GameMaker's blank template may create assets like `room1` that violate stricter project naming rules. Keep lint strict, then normalize imported/template assets explicitly:

```bash
gms maintenance normalize-names
gms maintenance normalize-names --fix
gms maintenance normalize-names --asset-type room --fix
```

The command uses the project's `.gms-mcp.json` naming config, defaults to dry-run, detects collisions, and performs real renames through the same reference-aware workflow as `gms workflow rename`.

Dev/test endpoint override:

```bash
GMS_MCP_TELEMETRY_ENDPOINT=https://localhost:8787/v1/events gms telemetry flush
```

## Local Development Setup

If you are working on the `gms-mcp` codebase itself, follow these steps to set up a local development environment:

1.  **Clone and install in editable mode**:
    ```bash
    git checkout dev
    uv sync --frozen --all-extras --python 3.12
    ```
    `gms-mcp` requires Python `3.10+`; we recommend Python `3.12` for local development.

2.  **Run the full local test suite**:
    ```bash
    uv run --frozen pytest -q
    ```

3.  **Initialize local and global MCP servers for testing**:
    We recommend setting up two separate MCP server configurations in Cursor to test your changes:
    
    *   **Global (`gms-global`)**: For general use across all your GameMaker projects.
    *   **Local (`gms-local`)**: Specifically for testing your current changes to the server.

    Run these commands from the project root (zsh/bash):
    ```bash
    # Global setup (names it 'gms-global' in Cursor)
    gms-mcp-init --cursor-global --server-name gms-global --mode python-module --python python3 --non-interactive

    # Local setup (names it 'gms-local' in Cursor)
    gms-mcp-init --cursor --server-name gms-local --mode python-module --python python3 --non-interactive
    ```

    PowerShell equivalent:

    ```powershell
    # Global setup (names it 'gms-global' in Cursor)
    gms-mcp-init --cursor-global --server-name gms-global --mode python-module --python python --non-interactive

    # Local setup (names it 'gms-local' in Cursor)
    gms-mcp-init --cursor --server-name gms-local --mode python-module --python python --non-interactive
    ```

4.  **Verify in Cursor**:
    Go to **Cursor Settings > Features > MCP** to see your new servers. You may need to click "Reload" or restart Cursor to see changes.

## Publishing (maintainers)

Publishing is chained to successful push-triggered CI on `dev`, `pre-release`, or `main`. It also requires passing real GameMaker 2024 and 2026 LTS certification artifacts from that exact CI run; skipped or missing certification blocks PyPI publication.

The `GAMEMAKER_ACCESS_KEY` secret belongs in the branch-restricted `gamemaker-ci` environment, not at repository scope. Maintainers can safely validate it with the CI workflow's `run_real_gamemaker_smoke` manual input: manually dispatched CI can run the licensed smoke matrix but cannot trigger publication.

Built package archives are checked against a public-file allowlist before publication. Development tests, plans, service operations, CI configuration, and local reports are excluded from PyPI artifacts.

## CI Coverage

- Core CI runs on Ubuntu and Windows across Python `3.10`-`3.13` from the committed `uv.lock`.
- Runner/session regression tests also run on macOS across Python `3.11`-`3.13`, including a mockless smoke test that builds a real `.app` bundle structure and validates executable path resolution.
- Core CI also runs a deterministic MCP tool smoke subset against a generated minimal GameMaker project fixture.
- CI runs pinned official MCP 2026-07-28 wire scenarios for stateless discovery, schema validation, caching, HTTP header routing, DNS-rebinding protection, tools, resources, prompts, concurrent streams, Resolve/input-required retries, capability checks, multi-round input, and tamper-resistant request state.
- CI audits every dependency resolved from `uv.lock` against the vulnerability database. The audit exports the locked graph first because `pip-audit --locked` does not read `uv.lock` directly.

### Quality Reports

Quality reports are generated during CI and published as `quality-reports-*` artifacts.

The reporting pipeline is subprocess-aware: CLI tests that launch `python -m gms_helpers.gms`
or other child processes now contribute to the final coverage artifacts instead of silently
dropping out of `coverage.xml`.

- `TEST_COVERAGE_REPORT.md`
- `MCP_TOOL_VALIDATION_REPORT.md`
- `mcp_tool_smoke_report.json`
- `coverage.xml`
- `pytest_results.xml`
- `quality_summary.json`

You can regenerate these locally with:

```bash
uv sync --frozen --all-extras
GMS_MCP_TOOLSETS=all uv run --frozen python scripts/run_mcp_tool_smoke.py \
  --init-minimal-base \
  --base-project build/mcp-smoke/base-project \
  --work-root build/mcp-smoke/work \
  --output build/reports/mcp_tool_smoke_report.json
uv run --frozen python scripts/generate_quality_reports.py
```

The MCP smoke uses a generated portable fixture and does not claim real compile/run coverage. The separate version-authored GameMaker fixtures provide that evidence. Release CI compiles those neutral fixtures on disposable Linux, Windows, and macOS runners. The generator enforces 85% overall coverage, 50% per-module coverage, runtime/source MCP registration parity, and reports executed MCP smoke calls separately from static test-source references.

Run both supported real GameMaker fixtures before promotion, for example:

```bash
uv run --frozen python scripts/run_real_gamemaker_smoke.py \
  --fixture-name gm-2024 \
  --expected-runtime-version 2024.14.4.268 \
  --required

uv run --frozen python scripts/run_real_gamemaker_smoke.py \
  --fixture-name gm-2026-lts \
  --expected-runtime-version 2026.0.0.23 \
  --required
```

## Use with a GameMaker project (multi-project friendly)

Run this inside each GameMaker project workspace (or repo) to generate config:

```bash
gms-mcp-init --cursor
```

This writes `.cursor/mcp.json` and attempts to auto-detect the `.yyp` location to set `GM_PROJECT_ROOT`.

Each MCP server process pins that detected project when it starts. Tool calls cannot switch the server to a sibling
project, traverse above the project, or follow a project symlink to files elsewhere on the host. Run a separate MCP
server entry for each project you want to expose. Sprite PNG inputs must also live inside that pinned project.

The pinned project is the server's approved data boundary, not a private area hidden from the connected MCP client.
Tools intentionally return asset metadata and source context from that project, so only pin a project whose contents
you are willing to send to the connected AI client or provider.

For a one-time setup that works across many projects, write Cursor's global config instead:

```bash
gms-mcp-init --cursor-global
```

Generate a Codex config from the current workspace:

```bash
gms-mcp-init --codex
```

Workspace Codex config stores `GM_PROJECT_ROOT` relative to the repository (`.` or a subdirectory such as
`gamemaker`) so `.codex/mcp.toml` can be committed without publishing a username or machine-specific path.
Project roots outside the workspace are rejected instead of being written as absolute paths.

Generate a global Codex entry in `~/.codex/config.toml`:

```bash
gms-mcp-init --codex-global
```

Global mode merges with existing entries so it is safe to keep multiple MCP servers in the same file.
It deliberately omits `GM_PROJECT_ROOT`, so each server pins the GameMaker project resolved from its own startup
workspace.

Inspect current Codex config resolution:

```bash
gms-mcp-init --codex-check
```

Human and JSON check output redact secret-like env, header, and credential argument values before printing.

Preview the redacted target Codex entries for local + global without writing. Existing unrelated
configuration is omitted, secret values are redacted, and machine-specific paths are replaced:

```bash
gms-mcp-init --codex-dry-run-only
```

Print Codex check output as JSON (useful for app automation):

```bash
gms-mcp-init --codex-check-json
```

One-shot Codex app setup (recommended for new workspaces):

```bash
gms-mcp-init --codex-app-setup
```

### Codex App Quickstart

1. Run `gms-mcp-init --codex-app-setup` in your GameMaker workspace.
2. Confirm the output says `Ready for Codex app: yes`.
3. If needed, run `gms-mcp-init --codex-check-json` and verify `active.scope` is `workspace`.
4. Use `gms-mcp-init --codex-dry-run-only` before changing global config to preview merged TOML safely.

## Canonical Client Workflow

All clients now support the same canonical action surface:

```bash
gms-mcp-init \
  --client <cursor|codex|claude-code|claude-desktop|antigravity|gemini|vscode|windsurf|openclaw|generic> \
  --scope <workspace|global> \
  --action <setup|check|check-json|app-setup>
```

Optional:
- `--config-path /custom/path` to override default config location
- `--safe-profile` to enforce conservative env defaults

Examples:

```bash
# Cursor setup + readiness check
gms-mcp-init --client cursor --scope workspace --action app-setup

# Codex machine-readable readiness
gms-mcp-init --client codex --scope workspace --action check-json

# Claude Desktop global plugin sync
gms-mcp-init --client claude-desktop --scope global --action setup

# Gemini alias (Antigravity path)
gms-mcp-init --client gemini --scope global --action app-setup

# OpenClaw app setup + workspace skills install
gms-mcp-init --client openclaw --scope workspace --action app-setup \
  --openclaw-install-skills --openclaw-skills-project
```

For parity status and supported defaults, see `documentation/CLIENT_SUPPORT_MATRIX.md`.

Generate example configs for other MCP-capable clients:

```bash
gms-mcp-init --vscode --windsurf --antigravity --openclaw
```

Set up Antigravity global config (recommended):

```bash
gms-mcp-init --antigravity-setup
```

This merges into `~/.gemini/antigravity/mcp_config.json`, writes atomically, creates a timestamped backup on overwrite, and enables a conservative safety profile by default:
- `GMS_MCP_ENABLE_DIRECT=0`
- `GMS_MCP_REQUIRE_DRY_RUN=1`

Check Antigravity readiness:

```bash
gms-mcp-init --antigravity-check
```

Print Antigravity check output as JSON:

```bash
gms-mcp-init --antigravity-check-json
```

Antigravity check output also redacts secret-like env, header, and credential argument values before printing.

One-shot Antigravity app setup:

```bash
gms-mcp-init --antigravity-app-setup
```

Use a custom Antigravity config path:

```bash
gms-mcp-init --antigravity-setup --antigravity-config-path /path/to/mcp_config.json
```

Opt in to the conservative safety profile for Antigravity example configs too:

```bash
gms-mcp-init --antigravity --safe-profile
```

When `GMS_MCP_REQUIRE_DRY_RUN=1` is set, you can allow specific destructive tools with:

```bash
export GMS_MCP_REQUIRE_DRY_RUN_ALLOWLIST=gm_safe_delete
```

Or generate everything at once:

```bash
gms-mcp-init --all
```

## Monorepos / multiple `.yyp`

If multiple `.yyp` projects are detected in a workspace:
- `gms-mcp-init` will warn and (when interactive) prompt you to pick one.
- In non-interactive environments, it defaults `GM_PROJECT_ROOT` to `${workspaceFolder}` (safe).

Force a specific project root:

```bash
gms-mcp-init --cursor --gm-project-root path/to/project
```

Preview output without writing files:

```bash
gms-mcp-init --cursor --dry-run
```

## Code Intelligence & Introspection

The MCP server provides comprehensive project analysis capabilities:

### GML Symbol Indexing (`gm_build_index`)
Build a high-performance index of all functions, enums, macros, and global variables in the project. This is required for advanced code intelligence tools.

### Symbol Definition (`gm_find_definition`)
Find the exact location and docstrings for any GML symbol in your project.

### Find References (`gm_find_references`)
Search for all usages of a specific function or variable across your entire codebase.

### List Symbols (`gm_list_symbols`)
List all project symbols with filtering by type, name substring, or file path.

### Asset Listing (`gm_list_assets`)
List all assets in your project, optionally filtered by type:
- **Supported types**: script, object, sprite, room, sound, font, shader, path, timeline, tileset, animcurve, sequence, note, folder, **particlesystem**, **extension**, **includedfile** (datafiles)

### Asset Reading (`gm_read_asset`)
Read the complete `.yy` JSON metadata for any asset by name or path.

### Reference Search (`gm_search_references`)
Search for patterns across project files with:
- **Scopes**: `all`, `gml`, `yy`, `scripts`, `objects`, `extensions`, `datafiles`
- **Modes**: literal string or regex
- **Options**: case sensitivity, max results

### Asset Graph (`gm_get_asset_graph`)
Build a dependency graph of assets with two modes:
- **Shallow (fast)**: Parses `.yy` files for structural references (parent objects, sprites, etc.)
- **Deep (complete)**: Also scans all GML code for runtime references like `instance_create`, `sprite_index`, `audio_play_sound`, etc.

### Texture Groups (`gm_texture_group_*`)
Create, inspect, and edit `.yyp` `TextureGroups`, plus bulk-assign assets (sprites/fonts/tilesets/etc) via `textureGroupId`.

Read-only tools:
- `gm_texture_group_list`: list texture groups + available configs (desktop/android/ios/etc)
- `gm_texture_group_read`: read a single texture group entry
- `gm_texture_group_members`: list assets in a group (top-level + ConfigValues overrides)
- `gm_texture_group_scan`: report missing groups referenced + mismatches (top-level vs config override)

Destructive tools (all support `dry_run=true`):
- `gm_texture_group_create`: clone an existing template group (default: `Default`)
- `gm_texture_group_update`: patch fields on a group (optionally per config via `ConfigValues`)
- `gm_texture_group_rename`: rename a group and rewrite asset references
- `gm_texture_group_delete`: blocks by default if referenced unless `reassign_to` is provided
- `gm_texture_group_assign`: bulk-assign assets by explicit list or filters

Config scope defaults:
- Assignment updates an asset's top-level `textureGroupId` **only when it is a dict** (null is left as-is).
- If `configs` is omitted, assignment updates only **existing** `ConfigValues` entries; pass `configs=[...]` to create explicit overrides.

### MCP Resources
Pre-built, cacheable project data for agents:
- `gms://project/index`: Complete project structure (assets, folders, room order, configs, audio/texture groups, IDE version)
- `gms://project/asset-graph`: Asset dependency graph
- `gms://system/updates`: Returns a human-readable message if a newer version of `gms-mcp` is available on PyPI or GitHub.

### Update Notifier
Shared update status is available through the MCP surfaces below, and supported client hooks can surface a once-daily reminder:
- **CLI**: `gms-mcp doctor` is the standard local diagnostics command. `gms-mcp doctor --notify` remains the update-only startup hook path.
- **Tool**: `gm_check_updates` returns structured update info.
- **Auto-check**: `gm_project_info` includes a cached `updates` field.
- **Resource**: `gms://system/updates` provides a quick text status.
- Plain `pip` installs are not guaranteed a proactive reminder unless the client setup includes the bundled startup hook.

Common doctor entry points:
- `gms-mcp doctor`: quick package/update/project-detection check.
- `gms-mcp doctor --project`: adds environment, runtime, license, and dependency checks.
- `gms-mcp doctor --full`: adds runtime selection and bridge status.
- `gms-mcp doctor --client codex|claude`: validates active client config for the current workspace.
- `gms-mcp doctor --project-root /path/to/project`: targets an explicit GameMaker project directory.
- `gms-mcp doctor --client codex --server-name gms-app`: validates a non-default MCP server entry name.
- `gms-mcp doctor --json`: emits a stable JSON report with `overall_status`, `exit_code`, and `checks`.

Automatic MCP diagnostic logs are stored outside GameMaker projects under
`~/.gms-mcp/logs/<opaque-project-id>/`. The directory name is a one-way hash of the project path,
and private directory/file permissions are applied where the operating system supports them.

### Runtime Management
Runtime list/pin/verify operations are exposed as MCP tools:
- `gm_runtime_list`
- `gm_runtime_pin`
- `gm_runtime_unpin`
- `gm_runtime_verify`

The plain `gms` CLI has runner commands (`gms run compile`, `gms run start`, `gms run stop`, `gms run status`), but does not expose separate runtime-management subcommands.

Runner runtime labels:
- `VM` and `GMS2 VM` map to Igor VM builds.
- `YYC` and `GMS2 YYC` map to Igor YYC builds.
- `GMRT` and `GMRT VM` are recognized and rejected with a clear error until GameMaker documents the Igor command-line syntax for GMRT targets.

Igor cache/temp paths are isolated by project and runtime. Confirmed pre-compile `System.AccessViolationException` runtime aborts clear that disposable state and retry up to three times; every attempt renews its single-use machine-lock delegation, while source compiler failures and post-compile exits are never retried. Post-mutation validation also recognizes GameMaker's packed platform-option payloads instead of treating them as malformed ordinary JSON. Igor child processes default to one reported .NET processor to avoid the 2026 LTS serializer/compiler race reproduced on macOS; set `GMS_MCP_IGOR_PROCESSOR_COUNT` to an integer from 1 to 256 to opt into more compiler parallelism.

On macOS, runner commands wait up to 30 seconds for any existing Igor build/run—including GameMaker IDE activity—to finish, then fail clearly instead of overlapping it. Set `GMS_MCP_IGOR_IDLE_WAIT_SECONDS` to a non-negative number of seconds; `0` enables immediate fail-fast behavior. Owned launches snapshot all existing `Mac_Runner` processes, recheck for a concurrent IDE Igor immediately after launch, and persist exact process identities plus an unguessable environment marker inherited through LaunchServices. Normal cleanup plus hard MCP/direct-CLI timeout cleanup can therefore remove newly spawned owned project-temp, bare Download, and log-tail helpers without touching pre-existing, concurrent user, or unrelated runners.

## CLI usage

Run from a project directory (or pass `--project-root`):

```bash
gms --version
gms --project-root . asset create script my_function --parent-path "folders/Scripts.yy"
gms --project-root . texture-groups list
gms --project-root . texture-groups assign game --type sprite --folder-prefix sprites/ --dry-run
```
