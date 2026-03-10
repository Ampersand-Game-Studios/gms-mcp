# Releasing `gms-mcp`

This project uses `setuptools-scm` + CI to control versions.

Policy:
- `main` publishes a **normal release** and bumps **patch** automatically (`X.Y.Z`).
- `dev` publishes **dev releases** (`X.Y.(Z+1).devN`).
- `pre-release` publishes **release candidates** (`X.Y.(Z+1)rcN`).
- **Post releases** (`X.Y.Z.postN`) are **manual only** and intended for packaging/deployment fixes (not code changes).

## Promotion flow

This repo promotes code in order:

1. `dev`
2. `pre-release`
3. `main`

Do not push ad-hoc release commits directly to `main`.

## Required validation before promotion

Run these from the repo root:

```bash
PYTHONPATH=src python cli/tests/python/run_all_tests.py
PYTHONPATH=src python -m pytest cli/tests/python/test_final_verification.py
python scripts/generate_quality_reports.py
```

The quality report script regenerates `build/reports/coverage.xml`, `TEST_COVERAGE_REPORT.md`,
`MCP_TOOL_VALIDATION_REPORT.md`, and `quality_summary.json`, and it merges subprocess coverage
data before writing the final report.

Before merging `pre-release` into `main`:

1. Stage `.github/next_tweet.txt` with the release post text.
2. Merge `pre-release` into `main`.
3. Confirm GitHub Actions `CI` passes on `main`.

## One-time: install tooling

```bash
python -m pip install -U build twine
```

## Local build

```bash
python -m build
```

Artifacts are created in `dist/`.

## First publish (manual)

PyPI Trusted Publishing cannot create a brand-new project: the project must exist first.

- Windows: `scripts/first_pypi_upload.ps1`
- macOS/Linux: `scripts/first_pypi_upload.sh`

These scripts build, validate, and upload from `dist/` using a PyPI API token.

## Ongoing publishes (automated): GitHub Trusted Publishing

Once the project exists on PyPI (name is `gms-mcp`, shown as `GMS-MCP` on PyPI), configure a Trusted Publisher:

1. On PyPI, open the project settings for `GMS-MCP`.
2. Add a Trusted Publisher for:
   - Owner: `Ampersand-Game-Studios`
   - Repository: `gms-mcp`
   - Workflow: `.github/workflows/publish.yml`
   - Environment: (leave blank unless you use one)
3. Push to `main` to publish a post-release automatically, or push a version tag like `v0.1.0` to set a new base version.

Notes:
- The GitHub Actions workflow publishes on every push to `main` (as requested). This will create many versions on PyPI.
- If you want fewer releases, change the workflow trigger to tags-only.

## Manual post-release (packaging fix only)

Use GitHub Actions `workflow_dispatch` for `Publish to PyPI` and provide an explicit version like `0.1.0.post1`.
