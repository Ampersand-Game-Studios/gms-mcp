# AGENTS.md

## Scope

This file applies to the `gms-mcp` repository root.

- Use `/Users/callum/Documents/Ampersand/Projects/GMS MCP/gms-mcp` as the working repo.
- The parent folder (`/Users/callum/Documents/Ampersand/Projects/GMS MCP`) is a separate empty git repo and should not be used for project changes.

## Branch Policy

- Do feature and fix work on `dev`.
- Promote changes by merging `dev -> pre-release -> main`.
- Do not push ad-hoc commits directly to `main`.

## Required Validation Before Promotion

- Run full Python test suite:
  - `PYTHONPATH=src python cli/tests/python/run_all_tests.py`
- Run final verification tests:
  - `PYTHONPATH=src python -m pytest cli/tests/python/test_final_verification.py`
- For release-bound updates, confirm GitHub Actions `CI` passes on `main`.

## Codex App Changes

- If you change Codex setup/check behavior in `src/gms_mcp/install.py`, also update:
  - `cli/tests/python/test_install_polish.py`
  - `README.md` Codex usage docs
- Keep both human output (`--codex-check`) and machine output (`--codex-check-json`) deterministic.
- Preserve dry-run safety: no file writes for `--dry-run` or `--codex-dry-run-only`.

## Release Tweet Flow

- For promotions to `main`, prepare `.github/next_tweet.txt` in advance.
- Keep tweet text aligned with `.github/x-personality.md`.
- The GitHub Action will post and then reset `.github/next_tweet.txt`.
