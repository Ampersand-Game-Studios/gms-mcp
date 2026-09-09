# GMS MCP

**Give your AI assistant tools to understand, edit, build, and interact with your GameMaker game.**

[![PyPI version](https://img.shields.io/pypi/v/gms-mcp)](https://pypi.org/project/gms-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/gms-mcp)](https://pypi.org/project/gms-mcp/)
[![CI](https://github.com/Ampersand-Game-Studios/gms-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Ampersand-Game-Studios/gms-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/LICENSE)

GMS MCP connects an MCP-capable AI client to a local GameMaker project. It gives the assistant structured operations for GameMaker assets and metadata, code navigation, project diagnostics, and Igor builds. An optional TCP bridge lets it send supported commands to a running game and read instrumented game logs.

Use it from Cursor, Codex, Claude Code, or another compatible client. Prefer the terminal? The package also includes the `gms` CLI; no AI client is required for CLI operations.

GMS MCP is an independent, open-source project by Ampersand Game Studios, not an official GameMaker product. It is a **game-development tool**, not a project-management or social-media service.

[Quick start](#quick-start) · [Capabilities](#what-you-can-do) · [Example workflows](#try-it-with-your-assistant) · [Safety and privacy](#safety-and-privacy) · [Troubleshooting](#troubleshooting) · [Documentation](#documentation)

## What you can do

| Task | How GMS MCP helps |
| --- | --- |
| Understand an unfamiliar project | Inspect assets, rooms, events, and metadata; find GML definitions and references; explore the project index and asset dependency graph. |
| Create and change game content | Create GameMaker assets, manage object events, place room instances, edit room layers, and organize audio/texture resources. |
| Refactor and maintain a project | Use reference-aware rename/delete workflows, check naming and resource integrity, and find orphaned or missing references. |
| Build and run | Compile and launch through GameMaker's Igor toolchain; select and pin installed runtimes; inspect and stop managed run sessions. |
| Interact with a running game | Install the optional bridge, send supported commands, and collect logs emitted through `__mcp_log()`. |
| Give the assistant reusable context | Expose MCP tools, project resources, five workflow prompts, and a project dashboard with optional MCP Apps rendering. |

Availability depends on the selected [tool profile](#enable-editing-and-additional-tools), client capabilities, and installed GameMaker toolchain. The bridge is not a GML hot-reload system, and GMS MCP does not provide automatic synchronization with the GameMaker IDE.

## Quick start

### 1. Install

You need **Python 3.10 or newer**, a GameMaker project containing a `.yyp` file, and an MCP-capable client. Building and running also require an installed GameMaker runtime, the appropriate licence/access credentials, and any target-specific SDKs. Project inspection does not require the GameMaker IDE to be running.

With [pipx](https://pipx.pypa.io/stable/how-to/install-pipx.html) installed:

```bash
pipx install gms-mcp
```

The package installs three commands:

| Command | Purpose |
| --- | --- |
| `gms-mcp` | Start the MCP server or run connection/environment diagnostics. |
| `gms-mcp-init` | Generate client configuration and check setup. |
| `gms` | Run GameMaker project operations directly from the terminal. |

For sprite image imports, install the optional image dependency with `pipx inject gms-mcp Pillow`.

### 2. Connect your client

Open a terminal in your **game's project folder**, not the GMS MCP source repository. Run the command for your client:

```bash
# Cursor
gms-mcp-init --client cursor --scope workspace --action app-setup

# Codex
gms-mcp-init --client codex --scope workspace --action app-setup --config-path .codex/config.toml

# Claude Code
gms-mcp-init --client claude-code --scope workspace --action app-setup
```

These canonical setup commands default to the **read-only `safe` profile**. They write client configuration; they do not grant the assistant project-editing or build tools. Read and complete any client registration instructions printed by the installer, then restart the client's MCP connection.

**Codex:** the explicit `--config-path` writes to `.codex/config.toml`, the project-scoped configuration supported by Codex for **trusted projects**. Without that override, the initializer writes a `.codex/mcp.toml` snippet that needs separate registration. Keep the override on subsequent setup/profile/check commands. Review existing configuration before merging, and only trust projects you recognize. See [OpenAI's MCP configuration guide](https://developers.openai.com/codex/mcp/).

Other installer targets include `antigravity` (alias `gemini`), `vscode`, `windsurf`, `openclaw`, and `generic`. Some targets generate configuration for you to import rather than activating a native client connection automatically. The `claude-desktop` target uses `--scope global` and generates a plugin bundle. Check the [compatibility matrix](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/COMPATIBILITY_MATRIX.md) for supported scopes and the [client guide](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/CLIENT_SUPPORT_MATRIX.md) for capability limits.

### 3. Verify the connection

From the same project folder:

```bash
gms-mcp doctor --project
gms-mcp-init --client cursor --scope workspace --action check
```

Replace `cursor` with your chosen client; for the Codex setup above, also add `--config-path .codex/config.toml`. Configuration checks do not prove that a client has connected: in a new assistant session, ask:

> Use GMS MCP to call `gm_capabilities` and `gm_project_info`. Confirm the connected project and available tools, then summarize the game without changing anything.

Successful tool responses from the intended project confirm the connection. Missing runtime or licence checks affect builds; they do not necessarily prevent read-only project inspection.

## Enable editing and additional tools

Start read-only to check the project boundary, then choose the access you need:

| Profile | Access |
| --- | --- |
| `safe` (default for canonical setup) | Read-only core tools. Project mutators and compile/run actions are omitted. |
| `standard` | Complete core toolset, including mutation and build workflows. |
| `full` | Core plus all optional toolsets. Separately gated integrations still require their own configuration. |

To enable editing and the wider tool catalogue for Cursor:

```bash
gms-mcp-init --client cursor --scope workspace --action app-setup --profile full
```

Use your chosen client and supported scope instead of `cursor`/`workspace` where appropriate. **`standard` and `full` allow writes and do not require every mutation to be a dry run.** Commit or back up your game first, avoid concurrent IDE edits, and restart the MCP connection after changing a profile. These profiles configure the MCP server, not the permissions of the standalone `gms` CLI or your AI client's other tools.

To expose selected domains instead of everything:

```bash
gms-mcp-init --client cursor --scope workspace --action app-setup --profile standard --toolsets core,assets,events,rooms
```

Optional domains: `assets`, `bridge`, `docs`, `events`, `maintenance`, `resourcetool`, `rooms`, `runtime`, and `texture-groups`. Call `gm_capabilities` to see what is actually enabled. `safe` accepts only the read-only core surface; it cannot be combined with extra toolsets.

## Try it with your assistant

These are example requests, not claims that an AI will complete every task correctly. Inspect the resulting changes and verification results.

**Understand the game** (available with `safe`):

> Inspect this project. Explain the startup room, main objects, and their relationships. Identify missing asset references without changing files.

**Add a feature** (enable `full` or the relevant editing domains):

> Add a collectible coin object using the existing project conventions. Put it in the correct asset folder, add its events, place one in the startup room, then validate the changes and compile. Report any remaining errors.

**Refactor with context** (requires editing access):

> Find every reference to `obj_enemy`. Preview a rename to `obj_enemy_basic`, explain what will change, and wait for my approval before applying it. Validate the project afterwards.

**Investigate a running game** (requires `bridge`, build access, and bridge setup):

> Check the bridge setup, run the game with the bridge enabled, verify the connection with a ping, and inspect recent instrumented logs. Stop the managed run when finished.

Clients that expose MCP prompts can also use `create-feature`, `diagnose-project`, `safe-refactor`, `compile-fix-retry`, and `inspect-live-game`. Fetching a prompt does not execute tools or modify the project; its instructions adapt to the active profile.

## Work with a running game

The optional bridge connects the MCP server to GML code inside your game over local TCP. Use it for supported runtime commands and instrumented logging, not arbitrary code hot reload.

1. Enable the `bridge` toolset and editing/build access.
2. Install the bridge assets and ensure a `__mcp_bridge` instance is created in the startup room. `gm_bridge_enable_one_shot` combines asset installation and room placement; `gm_bridge_install` alone does not place an instance.
3. Check the platform requirements in the [bridge guide](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/BRIDGE.md). Windows networking may require changing the GameMaker sandbox option; understand that change before applying it.
4. Run with `gm_run(background=true, enable_bridge=true)`, check `gm_bridge_status`, then send `ping` through `gm_run_command`.
5. Read `gm_run_logs` and stop the managed session with `gm_run_stop` when done.

Bridge logs come from `__mcp_log(...)`; they are **not** a scrape of every `show_debug_message(...)` or IDE console message. Only one game should use the bridge port at a time. Treat the bridge and its installed assets as development instrumentation; review or remove them before distributing your game.

## Use the CLI without an AI client

Run these from your game's project folder:

```bash
gms --help
gms --project-root . texture-groups list
gms maintenance normalize-names
```

The normalization command previews naming changes. Add `--fix` only when you intend to apply them. To create an asset or compile:

```bash
gms --project-root . asset create script my_function --parent-path "folders/Scripts.yy"
gms --project-root . run compile
```

Use an existing logical folder from your game in place of `folders/Scripts.yy`. Asset creation writes project files, and compilation requires the GameMaker toolchain. See the [CLI documentation](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/cli/docs/README.md) and `gms <command> --help` for available arguments.

## Safety and privacy

- **Choose the project deliberately.** Each MCP server process pins one GameMaker project at startup and checks project-relative access against that boundary. Use separate server entries for separate projects. Sprite PNG inputs must be inside the pinned project.
- **Project context goes to your client.** Tools intentionally return source and asset metadata from the selected game. Only connect a project whose contents you are willing to share with that AI client/provider. A local server does not make a cloud AI conversation private.
- **Use version control or backups.** Guarded operations, validation, and rollback mechanisms reduce risk; they do not guarantee that every AI edit is correct or recoverable. Avoid editing the same files simultaneously in the GameMaker IDE and through an assistant.
- **Usage telemetry is off by default.** Interactive CLI setup can ask for consent; MCP startup never prompts on stdio. Default usage events exclude paths, command arguments, output, project names, usernames, emails, hostnames, and persistent IDs. Check or disable it with `gms telemetry status` or `gms telemetry disable`.
- **Local does not mean offline.** Documentation lookup and update checks can access online services. SDK OpenTelemetry spans require a host-configured exporter; GMS MCP does not configure an external tracing service itself.
- **Keep diagnostics private.** Automatic MCP diagnostic logs live outside the game under `~/.gms-mcp/logs/<opaque-project-id>/`. Review logs and screenshots before sharing them; never attach credentials or proprietary game files to a public issue.

The generated client configurations use **stdio**, with the client starting a local server process. An optional bearer-authenticated **Streamable HTTP** transport is restricted to loopback, checks Host/Origin headers, and limits request bodies to 1 MiB. It is not a public or shared remote-server deployment mode. Follow the [HTTP configuration guide](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/CONFIGURATION.md#local-streamable-http); keep its token out of committed configuration and logs.

## Compatibility and limits

**GameMaker:** build/run defaults follow the host platform: Windows, macOS, or Linux. VM and YYC runtime labels are supported, subject to installed toolchains. GMRT labels are currently rejected because the required Igor command-line contract is not implemented. Runtime selection and pinning are available through `gm_runtime_list`, `gm_runtime_pin`, `gm_runtime_unpin`, and `gm_runtime_verify` in the `runtime` toolset.

**AI clients:** installer support means configuration generation and repository tests, not certification of every client release. Optional dashboard rendering, resource subscriptions, and Resolve choices depend on negotiated client capabilities. The dashboard also returns text and structured data without MCP Apps support.

**MCP:** the package pins Python SDK `mcp` and `mcp-types` to `2.2.0`. Compatibility tests cover protocol `2026-07-28` and legacy `2025-11-25`; SDK/package version numbers are distinct from protocol revision dates. Modern-mode features include cache hints, live resource updates after mutations or external edits, URI templates, and multi-round Resolve choices for exceptional mutations. See the [runtime capability contract](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/CLIENT_SUPPORT_MATRIX.md#runtime-capability-contract).

<details>
<summary>Optional official ResourceTool validation</summary>

This integration checks compatibility with YoYo's ResourceTool through an installed official `gm-cli`. It is disabled by default, is not an official affiliation, and is **not a mutation backend**.

Configure the server environment with the opt-in `resourcetool` toolset, an absolute executable path, its independently verified SHA-256, and the fixed argument contract:

```text
GMS_MCP_TOOLSETS=resourcetool
GMS_MCP_RESOURCETOOL_ENABLED=1
GMS_MCP_RESOURCETOOL_EXECUTABLE=<absolute path to the trusted gm-cli executable>
GMS_MCP_RESOURCETOOL_SHA256=<verified SHA-256 of that executable>
GMS_MCP_RESOURCETOOL_ARGUMENTS_JSON=["resourcetool","eval","resource list","{project_copy_yyp}"]
```

These are configuration values, not a shell script. Do not enable them in the read-only `safe` profile.

`gm_resourcetool_validate` requires the configured `gm-cli` executable to match its pinned SHA-256, rejects symlinks and private-file/content conventions, and copies only the `.yyp` descriptor into a task-owned temporary directory. It runs the fixed read-only command in an OS sandbox that blocks network access, live-project reads, and host writes; platforms without the required sandbox fail closed. Child output is suppressed, the minimal copy is checksummed before and after, and cleanup happens before returning. A rewrite, timeout, nonzero exit, ambiguous `.yyp`, identity mismatch, private data, or altered command contract fails closed. This validates ResourceTool project-list compatibility; it is not a mutation backend.

</details>

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The client cannot launch `gms-mcp` | Confirm the package is installed and its executables are on the client's PATH. Restart the client after installation. |
| Config exists, but no tools appear | Complete the client's registration/import step, restart its MCP connection, and call `gm_capabilities`. Installer readiness is a config check, not proof of a live connection. |
| Editing or build tools are missing | Check the active profile. `safe` intentionally omits them; select `standard`/`full` and restart. |
| The wrong project is detected | Run setup from the game workspace and specify `--gm-project-root path/to/game` when needed. Restart the server after changing the target. |
| A build fails | Run `gms-mcp doctor --full`; check the selected runtime, licence/access credentials, target SDKs, and returned compiler diagnostics. |
| The bridge runs but has no game connection or logs | Check the startup-room instance, networking requirements, port conflicts, and use of `__mcp_log()`. Follow the bridge guide before recompiling repeatedly. |

### Codex setup and checks

Use the same explicit configuration path as the quick start:

```bash
gms-mcp-init --client codex --scope workspace --action check --config-path .codex/config.toml
gms-mcp-init --client codex --scope workspace --action check-json --config-path .codex/config.toml
gms-mcp-init --client codex --scope workspace --action setup --config-path .codex/config.toml --dry-run
```

Checks redact secret-like values. Dry-run setup previews only the target server entry without writing, omitting unrelated config and replacing private paths. Workspace Codex configuration stores project roots relative to the repository; roots outside that workspace are rejected. Global configuration deliberately leaves project resolution to the server's startup workspace. The older `--codex-check`, `--codex-check-json`, and `--codex-dry-run-only` helpers target the initializer's default snippet/global paths, not the custom project config above.

### Updates

```bash
pipx upgrade gms-mcp
gms-mcp doctor
```

Restart your MCP connection after upgrading. `gm_check_updates` and `gms://system/updates` expose update status to clients. Bundled hooks can provide once-daily reminders where installed; not every package installation has an active reminder hook.

## Documentation

| Guide | Contents |
| --- | --- |
| [Configuration](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/CONFIGURATION.md) | Naming rules, project configuration, server transports, and runtime settings. |
| [Client support](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/CLIENT_SUPPORT_MATRIX.md) | Setup actions, scopes, and optional MCP capability behaviour. |
| [Compatibility matrix](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/COMPATIBILITY_MATRIX.md) | Generated installer/profile declarations and their test-evidence boundary. |
| [Live-game bridge](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/documentation/BRIDGE.md) | Installation, instrumentation, command workflow, and troubleshooting. |
| [Codex MCP configuration](https://developers.openai.com/codex/mcp/) | Official client configuration, project trust, and connection controls. |
| [CLI reference](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/cli/docs/README.md) | Direct command-line workflows. |
| [Changelog](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/CHANGELOG.md) | Project change history. |

The repository also includes a Claude plugin with workflow skills and hooks. The `gms skills install` command supports skill installation, including `gms skills install --openclaw --project` for workspace-scoped OpenClaw skills. Skills are instructions for the assistant, not additional server permissions.

## Development and verification

Contribute against `dev`; maintainers promote `dev` → `pre-release` → `main`. See [Contributing](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/CONTRIBUTING.md).

From a source checkout, using [uv](https://docs.astral.sh/uv/):

```bash
uv sync --frozen --all-extras --python 3.12
uv run --frozen pytest -q
uv run --frozen pytest cli/tests/python/test_final_verification.py
uv run --frozen python scripts/generate_quality_reports.py
```

CI runs core tests on Linux and Windows across Python 3.10–3.13, plus macOS runner/session tests across Python 3.11–3.13. It also checks MCP protocol behaviour, locked dependencies for known vulnerabilities, package privacy boundaries, and tool-registration parity. These checks are evidence of tested behaviour, not a guarantee that a project or dependency is free of defects.

Release publication requires passing **real GameMaker 2024 and 2026 LTS certification** from the exact push-triggered CI run on disposable Linux, Windows, and macOS runners. A generated MCP fixture alone does not establish compile/run compatibility. Build archives must also pass the public-file allowlist; local reports, service operations, development tests, and CI configuration are excluded from published packages.

<details>
<summary>Maintainer smoke tests and release gates</summary>

Run the full Python runner, final verification tests, and quality reports before promotion:

```bash
uv run --frozen python cli/tests/python/run_all_tests.py
uv run --frozen pytest cli/tests/python/test_final_verification.py
GMS_MCP_TOOLSETS=all uv run --frozen python scripts/run_mcp_tool_smoke.py \
  --init-minimal-base \
  --base-project build/mcp-smoke/base-project \
  --work-root build/mcp-smoke/work \
  --output build/reports/mcp_tool_smoke_report.json
uv run --frozen python scripts/generate_quality_reports.py
```

The report generator enforces 85% overall coverage, 50% per-module coverage, and runtime/source tool-registration parity. Executed MCP smoke calls are reported separately from static test-source references. Quality artifacts include the coverage/JUnit reports, `TEST_COVERAGE_REPORT.md`, `MCP_TOOL_VALIDATION_REPORT.md`, `mcp_tool_smoke_report.json`, and `quality_summary.json`.

On a configured GameMaker machine, run both version-authored fixtures:

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

Publication is chained to successful push-triggered CI on `dev`, `pre-release`, or `main`; skipped or missing real-GameMaker certification blocks PyPI publication. Keep `GAMEMAKER_ACCESS_KEY` in the branch-restricted `gamemaker-ci` environment, never in source or repository-wide configuration. A manually dispatched CI run with `run_real_gamemaker_smoke` can validate the licensed matrix but cannot trigger publication. Confirm release-bound CI passes on `main` after promotion.

</details>

## Support and licence

Report reproducible bugs or request features through [GitHub Issues](https://github.com/Ampersand-Game-Studios/gms-mcp/issues). Include the GMS MCP version, OS, client, GameMaker runtime if relevant, and sanitized reproduction steps. Use a minimal non-proprietary project rather than uploading your working game. Do not post secrets or exploitable security details publicly; use [GitHub's private vulnerability reporting](https://github.com/Ampersand-Game-Studios/gms-mcp/security) if available.

GMS MCP is released under the [MIT licence](https://github.com/Ampersand-Game-Studios/gms-mcp/blob/main/LICENSE). GameMaker and your AI client's own terms and licensing still apply. If the tools help you build your game, a [GitHub star](https://github.com/Ampersand-Game-Studios/gms-mcp) helps other developers find the project.
