# Releasing `gms-mcp`

This project uses `setuptools-scm` to generate the package version from git tags.

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

## Publish to PyPI

```bash
twine upload dist/*
```

### First publish helper scripts

- Windows: `scripts/first_pypi_upload.ps1`
- macOS/Linux: `scripts/first_pypi_upload.sh`

These build, validate, and upload from `dist/` using a PyPI API token.

## Recommended: GitHub “Trusted Publishing”

This repo can publish to PyPI via GitHub Actions without storing an API token.

High level steps:
1. Create the project on PyPI (`gms-mcp`).
2. In PyPI → “Publishing” → “Trusted publishers”, add this GitHub repo and workflow.
3. Push to `main` to publish a post-release automatically, or push a version tag like `v0.1.0` to set a new base version.

Notes:
- The GitHub Actions workflow publishes on every push to `main` (as requested). This will create many versions on PyPI.
- If you want fewer releases, change the workflow trigger to tags-only.
