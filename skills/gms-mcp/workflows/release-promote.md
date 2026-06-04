---
name: release-promote
description: Promote gms-mcp changes from dev to pre-release to main and publish the release post through X web UI
---

## When to use

Use this when taking completed `dev` branch work through `pre-release` and `main`.

## Release Promotion

1. Confirm the current repo is `gms-mcp` and the working tree is clean except intentional release changes.
2. Confirm the current branch is `dev`.
3. Run release validation:
   ```bash
   PYTHONPATH=src python cli/tests/python/run_all_tests.py
   PYTHONPATH=src python -m pytest cli/tests/python/test_final_verification.py
   python scripts/generate_quality_reports.py
   ```
4. Merge `dev` into `pre-release` and push.
5. Confirm GitHub Actions `CI` passes on `pre-release`.
6. Merge `pre-release` into `main` and push.
7. Confirm GitHub Actions `CI` and PyPI publishing pass on `main`.

## X Release Post

1. Draft the post from the released changes and `.github/x-personality.md`.
2. Use Chrome with the logged-in `@gms_mcp` account.
3. Publish through the X web UI.
4. Verify the post appears on the `@gms_mcp` profile.
5. Include the final X post URL in the release closeout.

## Rules

- Do not use the X API.
- Do not use GitHub Actions for X posting.
- Do not push ad-hoc commits directly to `main`.
- Do not report release completion until branch promotion, CI, publishing, and any requested X post are verified.
