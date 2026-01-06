# GMS MCP Tool Test Report
Date: 2026-01-05
Project: BLANK GAME

## Summary
Testing all 59 tools of the `gms-mcp` server.

## Final Status (All Tools Functional)

| Tool | Status | Notes |
|------|--------|-------|
| `gm_project_info` | [X] OK | Successfully retrieved project info. |
| `gm_mcp_health` | [X] OK | Health check passed. |
| `gm_cli` | [X] OK | CLI help command executed successfully. |
| `gm_check_updates` | [X] OK | Update check functional. |
| `gm_create_script` | [X] OK | Script created successfully. |
| `gm_create_object` | [X] OK | Created successfully (after using `o_` prefix). |
| `gm_create_sprite` | [X] OK | Sprite created successfully. |
| `gm_create_room` | [X] OK | Created successfully (after using `r_` prefix). |
| `gm_create_folder` | [X] OK | Folder created successfully. |
| `gm_create_font` | [X] OK | Font created successfully. |
| `gm_create_shader` | [X] OK | Created successfully (after using `sh_` prefix). |
| `gm_create_animcurve` | [X] OK | Animcurve created successfully. |
| `gm_create_sound` | [X] OK | Sound created successfully. |
| `gm_create_path` | [X] OK | Path created successfully. |
| `gm_create_tileset` | [X] OK | Created successfully (after using `ts_` prefix). |
| `gm_create_timeline` | [X] OK | Timeline created successfully. |
| `gm_create_sequence` | [X] OK | Sequence created successfully. |
| `gm_create_note` | [X] OK | Created successfully (after providing content). |
| `gm_maintenance_auto` | [X] OK | Comprehensive maintenance scan functional. |
| `gm_maintenance_lint` | [X] OK | Linting scan functional. |
| `gm_maintenance_validate_json` | [X] OK | JSON validation functional. |
| `gm_maintenance_list_orphans` | [X] OK | Orphan check functional. |
| `gm_maintenance_prune_missing` | [X] OK | Pruning scan (dry-run) functional. |
| `gm_maintenance_validate_paths` | [X] OK | Path validation functional. |
| `gm_maintenance_dedupe_resources` | [X] OK | Deduplication scan (dry-run) functional. |
| `gm_maintenance_sync_events` | [X] OK | Verified dry-run and fix modes (fixed `missing_fixed` key mismatch). |
| `gm_maintenance_clean_old_files` | [X] OK | Clean check functional. |
| `gm_maintenance_clean_orphans` | [X] OK | Clean check (dry-run) functional. |
| `gm_asset_delete` | [X] OK | Asset deletion and post-maintenance functional. |
| `gm_maintenance_fix_issues` | [X] OK | Verified functional. |
| `gm_room_ops_list` | [X] OK | Room listing functional. |
| `gm_room_layer_add` | [X] OK | Created successfully with correct JSON structure and depth support. |
| `gm_room_layer_list` | [X] OK | Listed layers successfully. |
| `gm_room_instance_add` | [X] OK | Added instance successfully with correct JSON structure. |
| `gm_room_instance_list` | [X] OK | Listed instances successfully. |
| `gm_room_ops_duplicate` | [X] OK | Room duplication functional. |
| `gm_room_ops_rename` | [X] OK | Room rename functional. |
| `gm_room_ops_delete` | [X] OK | Room deletion functional. |
| `gm_room_instance_remove` | [X] OK | Removed instance successfully. |
| `gm_room_layer_remove` | [X] OK | Removed layer successfully. |
| `gm_event_add` | [X] OK | Event addition functional. |
| `gm_event_list` | [X] OK | Event listing functional. |
| `gm_event_duplicate` | [X] OK | Implemented and verified (e.g., alarm:0 -> alarm:1). |
| `gm_event_validate` | [X] OK | Event validation functional. |
| `gm_event_fix` | [X] OK | Event fix functional. |
| `gm_event_remove` | [X] OK | Event removal functional (including `--keep-file`). |
| `gm_workflow_duplicate` | [X] OK | Workflow duplication functional. |
| `gm_workflow_rename` | [X] OK | Workflow rename functional. |
| `gm_workflow_swap_sprite` | [X] OK | Hardened for Windows file locks and no-ops. |
| `gm_workflow_delete` | [X] OK | Workflow deletion functional. |
| `gm_list_assets` | [X] OK | Asset listing functional. |
| `gm_read_asset` | [X] OK | Asset metadata reading functional. |
| `gm_search_references` | [X] OK | Reference searching functional. |
| `gm_get_asset_graph` | [X] OK | Dependency graph generation functional. |
| `gm_get_project_stats` | [X] OK | Project statistics functional. |
| `gm_compile` | [X] OK | Verified successful build using IDE-temp approach. |
| `gm_run` | [X] OK | Verified functional. |
| `gm_run_stop` | [X] OK | Functional and idempotent. |
| `gm_run_status` | [X] OK | Functional (ASCII only). |

## Observations & Fixed Issues
1. **Naming Conventions**: Creation tools correctly enforce strict naming prefixes (`o_`, `r_`, `sh_`, `ts_`).
2. **Room & Instance Tools**: FIXED `AttributeError: 'Namespace' object has no attribute 'room'` by correcting CLI argument wiring and MCP parameter mapping.
3. **Tileset & JSON structure**: FIXED Igor compilation errors by ensuring strict field ordering (`tileAnimationFrames` before `tileAnimation`) and adding required `$GM...` type tags for room layers and instances.
4. **Event Duplication**: FIXED by implementing `duplicate_event` in the core helper.
5. **Windows Robustness**: FIXED `PermissionError` in `gm_workflow_swap_sprite` using temporary files and retries; made `gm_run_stop` idempotent.
6. **Igor CLI**: FIXED "file name not provided" error by correcting the `/of=` parameter format and ensuring a consistent compilation pipeline using the `PackageZip` action.
7. **Environment Health**: Verified that all tools now pass when run against the `BLANK GAME` project.
