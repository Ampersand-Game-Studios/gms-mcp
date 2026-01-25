# GM Lint GML

## Status
**Partially Implemented** | Claude Code Skill: Available

## Overview
Checks for common GML-specific errors or anti-patterns that JSON linting doesn't catch.

## Current Implementation
The following tools provide partial linting capability:
- `gms diagnostics --depth deep` - Project-wide diagnostics
- `gms maintenance lint` - JSON/naming convention checks
- `gms maintenance auto --fix` - Auto-fix safe issues

## Claude Code Skill
A workflow skill (`lint-gml.md`) is available via `gms skills install`. This skill provides:
- Guidance on running diagnostics
- Common GML anti-patterns to watch for (variable scope, performance, type safety)
- Integration patterns for CI/pre-commit workflows

## Goals (Remaining)
- ~~Check for "Missing Prefix" conventions (e.g., an object not starting with `o_`).~~ ✓ Implemented
- Check for missing `event_inherited()` in child objects.
- Detect unused local variables.
- Detect hardcoded magic numbers.
- GML-specific semantic analysis (not just naming/JSON).

## Proposed MCP Tool
`gm_lint_gml(scope: str = "project", rules: list = None)`

## Potential Implementation
1. Define a set of "Lint Rules" for GML (configurable).
2. Build lightweight GML AST or use regex patterns for semantic checks.
3. Scan all `.gml` files in the project.
4. Return a list of warnings/errors with line numbers and suggested fixes.
