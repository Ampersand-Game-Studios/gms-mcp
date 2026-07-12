---
name: release-promote
description: Validate and promote one gms-mcp commit through dev, pre-release, and main release channels
---

## When to use

Use this only when promoting completed repository work through the supported PyPI channels.

## Preconditions

1. Confirm the repository is `gms-mcp`, the intended commit is on `dev`, and the working tree contains no unintended changes.
2. Confirm the GameMaker-ready runner has distinct configured fixture paths for 2024 and 2026 LTS, with exact expected runtime versions.
3. Do not promote a different commit at a later branch stage.

## Local validation

Run from the repository root:

```bash
uv sync --frozen --all-extras
uv run pytest -q
uv run ruff check .
uv run pyright
GMS_MCP_TOOLSETS=all GMS_MCP_POST_MUTATION_VERIFY=off uv run python3 scripts/run_mcp_tool_smoke.py --init-minimal-base --base-project build/mcp-smoke/base-project --work-root build/mcp-smoke/work --output build/reports/mcp_tool_smoke_report.json
uv run python3 scripts/generate_quality_reports.py --output-dir build/reports
```

Run and retain both real GameMaker fixture reports. Replace the example paths and versions with the exact configured values; do not use a version prefix as if it were exact certification.

```bash
GMS_MCP_REAL_SMOKE_PROJECT=/path/to/distinct-gm-2024-fixture GMS_MCP_REAL_SMOKE_EXPECTED_RUNTIME=2024.14.4.268 uv run python3 scripts/run_real_gamemaker_smoke.py --fixture-name gm-2024 --required --output build/reports/real_gamemaker_smoke-gm-2024.json
GMS_MCP_REAL_SMOKE_PROJECT=/path/to/distinct-gm-2026-lts-fixture GMS_MCP_REAL_SMOKE_EXPECTED_RUNTIME=2026.0.0.23 uv run python3 scripts/run_real_gamemaker_smoke.py --fixture-name gm-2026-lts --required --output build/reports/real_gamemaker_smoke-gm-2026-lts.json
uv run python3 scripts/verify_release_certification.py build/reports --expected gm-2024 gm-2026-lts
```

Stop if either fixture is missing, skipped, malformed, uses the wrong runtime, or fails any required check.

## Promotion and publication

1. Push the validated commit to `dev`.
2. Verify the push-triggered `CI` workflow succeeds for that exact SHA.
3. Verify `Publish to PyPI` consumed that CI run's artifacts and published the expected `.devN` version.
4. Merge that same commit into `pre-release`, push, and repeat the exact-SHA CI and publication checks for the `rcN` version.
5. Merge that same commit into `main`, push, and repeat the exact-SHA CI and publication checks for the final patch version.

The publication workflow is chained from successful push CI on all three branches. Pull-request CI must never publish. A successful branch push alone is not evidence of publication.

## Optional X release post

1. Draft the exact post from the published changes and `.github/x-personality.md`.
2. Before posting, present a final confirmation recap containing the sending account (`@gms_mcp`), target/profile, exact body, and every attachment. Do not post until the user confirms that exact recap.
3. Use Chrome with the existing logged-in `@gms_mcp` session; do not use the X API.
4. Verify the exact post appears on the `@gms_mcp` profile and include its URL in the closeout.

## Completion contract

- The same commit passed local validation and both distinct real fixtures.
- CI passed for the exact SHA on every promoted branch.
- Each intended channel version appears on PyPI and is tied to the corresponding CI artifacts.
- Any requested X post was confirmed before sending and verified afterward.
- No ad-hoc release commit was pushed directly to `main`.
