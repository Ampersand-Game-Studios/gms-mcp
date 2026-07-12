# Releasing `gms-mcp`

`setuptools-scm` owns package versions. Branch promotion and PyPI publication are automated, but publication is fail-closed behind both portable CI and real GameMaker certification.

## Release channels

- `dev` publishes `X.Y.(Z+1).devN`.
- `pre-release` publishes `X.Y.(Z+1)rcN`.
- `main` publishes the next final patch, `X.Y.(Z+1)`.

Promote in this order: `dev` → `pre-release` → `main`. Do not push ad-hoc release commits directly to `main`.

## Automated release gate

The `Publish to PyPI` workflow does not run directly on a branch push. It runs only after a successful push-triggered `CI` workflow for the same commit, downloads that CI run's immutable artifacts, and requires both real GameMaker fixtures to report `status: passed`:

- `gm-2024`
- `gm-2026-lts`

A missing, skipped, malformed, or failed real-smoke report blocks publication. Pull-request CI runs never publish.

Configure the GameMaker-ready self-hosted runner before enabling release automation:

- `GMS_MCP_REAL_SMOKE_RUNNER_LABELS`: JSON labels for a GameMaker-ready runner, for example `["self-hosted","macOS","ARM64","gamemaker"]`.
- `GMS_MCP_REAL_SMOKE_PROJECT_2024`: set only in the runner's local `.env` to the absolute path of a valid 2024 fixture.
- `GMS_MCP_REAL_SMOKE_PROJECT_2026`: set only in the runner's local `.env` to the absolute path of a valid 2026 LTS fixture.

Fixture paths are deliberately runner-local: do not store them in repository variables or committed workflow files. CI pins the certified runtimes and fails closed when either fixture, runtime, or runner is unavailable.

## Local validation before promotion

Run from the repository root:

```bash
uv sync --frozen --all-extras
uv run pytest -q
GMS_MCP_TOOLSETS=all uv run python3 scripts/run_mcp_tool_smoke.py \
  --init-minimal-base \
  --base-project build/mcp-smoke/base-project \
  --work-root build/mcp-smoke/work \
  --output build/reports/mcp_tool_smoke_report.json
uv run python3 scripts/generate_quality_reports.py
```

Run each supported real fixture with its intended runtime:

```bash
GMS_MCP_REAL_SMOKE_PROJECT=/path/to/gm-2024 \
GMS_MCP_REAL_SMOKE_EXPECTED_RUNTIME='2024.*' \
uv run python3 scripts/run_real_gamemaker_smoke.py --fixture-name gm-2024 --required

GMS_MCP_REAL_SMOKE_PROJECT=/path/to/gm-2026-lts \
GMS_MCP_REAL_SMOKE_EXPECTED_RUNTIME='2026.*' \
uv run python3 scripts/run_real_gamemaker_smoke.py --fixture-name gm-2026-lts --required
```

The quality generator enforces 85% overall statement coverage, 50% per-module coverage, runtime/source MCP registration parity, and reports dedicated MCP smoke calls separately from static test-source references.

## Promotion

1. Confirm local validation and both real fixtures pass.
2. Promote the same commit through `dev`, `pre-release`, and `main` as appropriate.
3. Confirm the branch's `CI` run passes.
4. Confirm `Publish to PyPI` consumed that CI run and published the expected channel version.
5. If a release post is wanted, draft it using `.github/x-personality.md`, publish through the X web UI while logged into `@gms_mcp`, and verify it appears on the profile.

GitHub Actions does not post to X.

## First PyPI publish

Trusted Publishing cannot create a new PyPI project. For the first upload only:

- Windows: `scripts/first_pypi_upload.ps1`
- macOS/Linux: `scripts/first_pypi_upload.sh`

After the project exists, configure PyPI Trusted Publishing for:

- Owner: `Ampersand-Game-Studios`
- Repository: `gms-mcp`
- Workflow: `.github/workflows/publish.yml`
