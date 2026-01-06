"""Commands package for GMS Master CLI."""

from .maintenance_commands import (
    handle_maintenance_auto,
    handle_maintenance_lint,
    handle_maintenance_validate_json,
    handle_maintenance_list_orphans,
    handle_maintenance_prune_missing,
    handle_maintenance_validate_paths,
    handle_maintenance_dedupe_resources,
    handle_maintenance_sync_events,
    handle_maintenance_clean_old_files,
    handle_maintenance_clean_orphans,
    handle_maintenance_fix_issues,
)
from .diagnostics_commands import handle_diagnostics
from .runner_commands import (
    handle_runner_compile,
    handle_runner_run,
    handle_runner_stop,
    handle_runner_status,
)
from .asset_commands import (
    handle_asset_create,
    handle_asset_delete,
)
from .event_commands import (
    handle_event_add,
    handle_event_remove,
    handle_event_duplicate,
    handle_event_list,
    handle_event_validate,
    handle_event_fix,
)
from .room_commands import (
    handle_room_layer_add,
    handle_room_layer_remove,
    handle_room_layer_list,
    handle_room_duplicate,
    handle_room_rename,
    handle_room_delete,
    handle_room_list,
    handle_room_instance_add,
    handle_room_instance_remove,
    handle_room_instance_list,
)
from .workflow_commands import (
    handle_workflow_duplicate,
    handle_workflow_rename,
    handle_workflow_delete,
    handle_workflow_swap_sprite,
)
