# Test Coverage Report
Date: 2026-01-05
Project: gms-mcp

## Summary
The test suite consists of 342 unit and integration tests, covering asset management, project maintenance, room operations, and CLI/MCP infrastructure.

| Metric | Value |
|--------|-------|
| **Total Tests** | 342 |
| **Pass Rate** | 100% |
| **Overall Statement Coverage** | 36% |
| **Test Duration** | 11.56s |

## Coverage Breakdown by Component

### Core Logic (`gms_helpers`)
The core logic resides in the `gms_helpers` package and shows high reliability in critical asset manipulation areas.

| Module | Coverage | Notes |
|--------|----------|-------|
| `assets.py` | 64% | Asset creation templates and logic. |
| `auto_maintenance.py` | 79% | Automated project cleanup and validation. |
| `base_asset.py` | 91% | Base class for all GameMaker assets. |
| `event_helper.py` | 43% | Event addition, removal, and duplication. |
| `introspection.py` | 84% | Logic for reading project structure and finding assets. |
| `reference_scanner.py` | 83% | Critical logic for updating asset references during renames. |
| `room_layer_helper.py` | 54% | Management of layers within rooms. |
| `utils.py` | 71% | JSON parsing, filesystem utilities, and naming validation. |
| `workflow.py` | 56% | High-level operations like Duplicate and Rename. |

### MCP Server Infrastructure (`gms_mcp`)
Coverage in this area is lower due to the repetitive nature of tool definitions which primarily wrap the `gms_helpers` logic.

| Module | Coverage | Notes |
|--------|----------|-------|
| `gamemaker_mcp_server.py` | 12% | Standard MCP tool wrappers (3,000+ lines). |
| `execution_policy.py` | 100% | Policy logic for allowed operations. |
| `update_notifier.py` | 86% | Logic for checking newer versions on PyPI. |

### Low Coverage Areas & Mocking
Some modules show lower coverage due to heavy reliance on external state or binary executables that are mocked in the test environment:
- **`runner.py` (9%)**: Interfaces with `Igor.exe`.
- **`asset_helper.py` (8%)**: Contains CLI legacy functions and complex filesystem interactions.
- **`install.py` (0-17%)**: Installation scripts designed for one-time environment setup.

## Recommendations for Improvement
1. **MCP Wrapper Tests**: Increase coverage for `gamemaker_mcp_server.py` by adding more integration tests that call the tools through the MCP interface rather than testing the helper functions directly.
2. **Event Duplication**: Extend tests for the newly implemented `duplicate_event` logic.
3. **Runner Mocking**: Improve the `Igor.exe` mock suite to test more edge cases in the compilation pipeline without requiring a full GameMaker installation.

---
*Report generated automatically following full test suite execution.*
