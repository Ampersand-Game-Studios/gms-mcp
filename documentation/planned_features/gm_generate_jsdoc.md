# GM Generate JSDoc

## Overview
Automatically generates IDE-compliant documentation headers (`@param`, `@returns`, `@description`) for GML scripts.

## Goals
- Scan script body for argument usage (`argument0`, `var _val = argument[0]`, or named parameters).
- Detect return types.
- Format results as a standard GameMaker JSDoc comment block.

## Proposed MCP Tool
`gm_generate_jsdoc(script_name: str, apply: bool = False)`

## Potential Implementation
1. Read the `.gml` file content.
2. Analyze the function signature and body.
3. Prepend the generated comment block to the file.
