# Split Legacy Helper Surfaces

## Goal

Refactor the large GMS MCP helper surfaces into smaller, testable modules while preserving CLI/MCP behavior, GameMaker project safety, dry-run guarantees, telemetry/redaction behavior, and existing coverage.

## Starting State

- Repo: `/Users/callum/Projects/Ampersand Game Studios/GMS MCP/gms-mcp`
- Branch: `dev`
- Starting branch status: clean
- Target modules:
  - `src/gms_helpers/texture_groups.py`
  - `src/gms_helpers/assets.py`
  - `src/gms_helpers/asset_helper.py`
  - `src/gms_helpers/runner.py`
  - `src/gms_mcp/install.py`

## Assumptions

- Internal callers should be updated to the new modules instead of keeping compatibility layers.
- Thin public entry modules are acceptable only where existing CLI/MCP/tests/public imports require them.
- No new dependency is expected.
- Real GameMaker smoke may be unavailable locally; if unavailable, record it as residual risk.

## Split Checklist

- [x] Split `texture_groups.py`.
- [x] Split `assets.py`.
- [x] Split `asset_helper.py`.
- [x] Split `runner.py`.
- [x] Split `gms_mcp/install.py`.
- [x] Run focused validation after each split.
- [x] Run final validation suite.
- [x] Commit coherent checkpoints.
- [x] Record rollback notes and residual risk.

## Validation Plan

Focused texture/assets workflow:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_texture_groups.py cli/tests/python/test_assets_texture_workflow_95.py cli/tests/python/test_asset_texture_workflow_gap_coverage.py -q
```

Focused asset helper workflow:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_assets_comprehensive.py cli/tests/python/test_asset_helper.py cli/tests/python/test_asset_helper_additional_coverage.py cli/tests/python/test_asset_helper_command_coverage.py -q
```

Focused runner workflow:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_runner_95_coverage.py cli/tests/python/test_runner_gap_coverage.py cli/tests/python/test_runner_session_integration.py -q
```

Focused install workflow:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_install_parity.py cli/tests/python/test_install_polish.py cli/tests/python/test_install_wrapper_coverage.py -q
```

Final validation:

```bash
PYTHONPATH=src ./.venv/bin/python cli/tests/python/run_all_tests.py
PYTHONPATH=src ./.venv/bin/python -m pytest cli/tests/python/test_final_verification.py
./.venv/bin/python -m ruff check .
./.venv/bin/pyright
./.venv/bin/python scripts/generate_quality_reports.py
```

## Progress

- Created this progress log on `dev`.
- Split `src/gms_helpers/texture_groups.py` into a thin public facade plus:
  - `src/gms_helpers/texture_group/project.py`
  - `src/gms_helpers/texture_group/refs.py`
  - `src/gms_helpers/texture_group/scan.py`
  - `src/gms_helpers/texture_group/mutations.py`
- Updated MCP texture-group wrappers to import the split implementation modules directly.
- Updated texture-group tests to patch the new implementation module paths.
- Validation passed:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_texture_groups.py cli/tests/python/test_assets_texture_workflow_95.py cli/tests/python/test_asset_texture_workflow_gap_coverage.py cli/tests/python/test_mcp_wrapper_translation.py -q
```

Result: `35 passed, 23 subtests passed`.
- Split `src/gms_helpers/assets.py` into a thin public facade plus:
  - `src/gms_helpers/asset_types/code.py`
  - `src/gms_helpers/asset_types/visual.py`
  - `src/gms_helpers/asset_types/project.py`
  - `src/gms_helpers/asset_types/media.py`
  - `src/gms_helpers/asset_types/registry.py`
- Preserved the existing `gms_helpers.assets.get_config` patch/import surface through the facade.
- Updated internal source imports to use `gms_helpers.asset_types` directly.
- Validation passed:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_assets_comprehensive.py cli/tests/python/test_asset_helper.py cli/tests/python/test_asset_helper_additional_coverage.py cli/tests/python/test_asset_helper_command_coverage.py cli/tests/python/test_assets_texture_workflow_95.py cli/tests/python/test_asset_texture_workflow_gap_coverage.py cli/tests/python/test_workflow.py cli/tests/python/test_workflow_enhanced.py cli/tests/python/test_sprite_multiframe.py -q
```

Result: `173 passed, 103 subtests passed`.
- Split `src/gms_helpers/asset_helper.py` into a thin public facade plus:
  - `src/gms_helpers/asset_cli/context.py`
  - `src/gms_helpers/asset_cli/create.py`
  - `src/gms_helpers/asset_cli/delete.py`
  - `src/gms_helpers/asset_cli/maintenance.py`
  - `src/gms_helpers/asset_cli/parser.py`
- Updated internal command modules to import the split asset CLI implementations directly.
- Updated asset-helper tests to patch the owning implementation modules instead of the facade.
- Validation passed:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_asset_helper.py cli/tests/python/test_asset_helper_additional_coverage.py cli/tests/python/test_asset_helper_command_coverage.py cli/tests/python/test_maintenance_purge.py cli/tests/python/test_command_modules_comprehensive.py -q
```

Result: `60 passed, 80 subtests passed`.
- Split `src/gms_helpers/runner.py` into a thin public facade plus:
  - `src/gms_helpers/runner_support/targets.py`
  - `src/gms_helpers/runner_support/discovery.py`
  - `src/gms_helpers/runner_support/artifacts.py`
  - `src/gms_helpers/runner_support/igor.py`
  - `src/gms_helpers/runner_support/macos.py`
  - `src/gms_helpers/runner_support/execution.py`
- Kept `GameMakerRunner` and convenience functions exported from `gms_helpers.runner`.
- Updated runner tests to patch the owning implementation modules.
- Validation passed:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_runner_95_coverage.py cli/tests/python/test_runner_gap_coverage.py cli/tests/python/test_runner_session_integration.py cli/tests/python/test_igor_platform_mapping.py -q
```

Result: `57 passed`.
- Split `src/gms_mcp/install.py` into a public CLI entrypoint plus:
  - `src/gms_mcp/install_support/common.py`
  - `src/gms_mcp/install_support/client_configs.py`
  - `src/gms_mcp/install_support/flow.py`
  - `src/gms_mcp/install_support/project.py`
  - `src/gms_mcp/install_support/naming.py`
- Kept `gms_mcp.install.main` and existing importable helper names available from the entry module where tests/public imports rely on them.
- Updated install tests to patch the owning support modules for split helper behavior.
- Validation passed:

```bash
./.venv/bin/python -m pytest cli/tests/python/test_install_parity.py cli/tests/python/test_install_polish.py cli/tests/python/test_install_wrapper_coverage.py cli/tests/python/test_bridge_install_coverage.py -q
```

Result: `73 passed, 33 subtests passed`.
- Final validation passed:

```bash
PYTHONPATH=src ./.venv/bin/python cli/tests/python/run_all_tests.py
PYTHONPATH=src ./.venv/bin/python -m pytest cli/tests/python/test_final_verification.py
./.venv/bin/python -m ruff check .
./.venv/bin/pyright
./.venv/bin/python scripts/generate_quality_reports.py
```

Results:
  - `run_all_tests.py`: `Passed: 75/75`, `Failed: 0/75`.
  - `test_final_verification.py`: `3 passed`.
  - `ruff check .`: `All checks passed`.
  - `pyright`: `0 errors, 2 warnings` for existing dynamic `__all__` facades.
  - `generate_quality_reports.py`: `965 passed, 1 warning, 210 subtests passed`; report generation completed.

## Current Known Issues

- None found in validation.

## Rollback Notes

- Checkpoint commits:
  - `9dc0e5a` Split texture group helpers
  - `1cc6379` Split asset type implementations
  - `ddb0db5` Split asset helper CLI
  - `536985f` Split runner implementation
  - `28f2c2f` Split install support modules
- The final validation fixups are separate from the split checkpoints.
- Each split can be reverted independently if a regression is isolated to that surface.

## Residual Risk

- Real GameMaker smoke coverage depends on local `GMS_MCP_REAL_SMOKE_PROJECT` / runtime availability; the automated suite exercised the configured smoke tests and skipped unavailable real-project paths as designed.
- `GameMakerRunner` now composes mixins; pyright needs scoped dynamic-attribute suppression in those mixin modules because the attributes are supplied by the final composed class.
