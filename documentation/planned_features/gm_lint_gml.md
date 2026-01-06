# GM Lint GML

## Overview
Checks for common GML-specific errors or anti-patterns that JSON linting doesn't catch.

## Goals
- Check for missing `event_inherited()` in child objects.
- Detect unused local variables.
- Check for "Missing Prefix" conventions (e.g., an object not starting with `o_`).
- Detect hardcoded magic numbers.

## Proposed MCP Tool
`gm_lint_gml(scope: str = "project")`

## Potential Implementation
1. Define a set of "Lint Rules" for GML.
2. Scan all `.gml` files in the project.
3. Return a list of warnings/errors with line numbers.
