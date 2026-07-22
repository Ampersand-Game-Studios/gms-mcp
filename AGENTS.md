# AGENTS.md

## Scope

This file applies to the `gms-mcp` repository root.

- Use the `gms-mcp` repository root (the directory containing this file) as the working repo.
- The parent folder is a separate empty git repo and should not be used for project changes.

## Branch Policy

- Do feature and fix work on `dev`.
- Promote changes by merging `dev -> pre-release -> main`.
- Do not push ad-hoc commits directly to `main`.

## Required Validation Before Promotion

- Run full Python test suite:
  - `PYTHONPATH=src python cli/tests/python/run_all_tests.py`
- Run final verification tests:
  - `PYTHONPATH=src python -m pytest cli/tests/python/test_final_verification.py`
- Run quality reports and coverage gates:
  - `python scripts/generate_quality_reports.py`
- On a machine with GameMaker installed, run real compile smoke:
  - `uv run python3 scripts/run_real_gamemaker_smoke.py --fixture-name gm-2024 --expected-runtime-version 2024.14.4.268 --required`
  - `uv run python3 scripts/run_real_gamemaker_smoke.py --fixture-name gm-2026-lts --expected-runtime-version 2026.0.0.23 --required`
- For release-bound updates, confirm GitHub Actions `CI` passes on `main`.

## Codex App Changes

- If you change Codex setup/check behavior in `src/gms_mcp/install.py`, also update:
  - `cli/tests/python/test_install_polish.py`
  - `README.md` Codex usage docs
- Keep both human output (`--codex-check`) and machine output (`--codex-check-json`) deterministic.
- Preserve dry-run safety: no file writes for `--dry-run` or `--codex-dry-run-only`.
