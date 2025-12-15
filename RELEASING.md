# Releasing `gms-mcp`

This project uses `setuptools-scm` to generate versions from git tags.

- Tag releases like `v0.1.0`, `v0.2.0`, etc.
- Commits after a tag become automatic post-releases, e.g. `0.1.0.post3`.
  This supports publishing on every `main` commit without manually bumping versions.

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
