# Extension and Datafile Mutation

## Overview
Expands the toolset to include adding, modifying, and deleting Extensions and Included Files (Datafiles).

## Goals
- `gm_import_datafile`: Copy an external file into `datafiles/` and register it in the `.yyp`.
- `gm_create_extension`: Basic stub for GML/Javascript/DLL extensions.
- Support deep search/introspection for extension code.

## Proposed MCP Tools
- `gm_import_datafile(source_path: str, destination_folder: str)`
- `gm_delete_datafile(file_name: str)`

## Implementation Details
1. Extend `AssetHelper` to handle `GMExtension` and `GMIncludedFile`.
2. Update `.yyp` resource registration logic to handle these non-standard asset types.
