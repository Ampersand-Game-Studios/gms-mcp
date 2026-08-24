"""Outcome-oriented MCP prompt templates for safe GameMaker work."""

from __future__ import annotations

from typing import Any


PROMPT_NAMES = (
    "create-feature",
    "diagnose-project",
    "safe-refactor",
    "compile-fix-retry",
    "inspect-live-game",
)


def register(
    mcp: Any,
    *,
    enabled_toolsets: tuple[str, ...] = ("core",),
    read_only: bool = False,
) -> None:
    """Register the stable five-prompt GameMaker workflow catalogue."""
    enabled = set(enabled_toolsets)
    feature_goal = (
        "Implement the requested GameMaker feature as a complete, verifiable change."
        if not read_only
        else "Produce a read-only implementation plan for the requested GameMaker feature."
    )
    refactor_goal = (
        "Perform the requested GameMaker refactor narrowly and preserve project structure."
        if not read_only
        else "Produce a narrow, evidence-backed refactor plan without changing the project."
    )
    compile_goal = (
        "Resolve a GameMaker compile failure with evidence-led retries."
        if not read_only
        else "Diagnose the reported compile failure from existing project evidence without compiling or editing."
    )
    live_goal = (
        "Inspect the running GameMaker game using only supported, evidence-safe bridge operations."
        if not read_only
        else "Assess live-inspection readiness without starting, stopping, connecting to, or changing the game."
    )
    asset_workflow = (
        "The `assets` toolset is active. Before creating assets, identify an existing logical folder; if none fits, "
        "create the folder first with `gm_create_folder`, then pass its folder `.yy` path as `parent_path` to every "
        "related `gm_create_*` call. Do not leave new assets at the project root."
        if "assets" in enabled and not read_only
        else "Asset-creation tools are not active in this server profile. Do not attempt `gm_create_*` calls; report that "
        "the `assets` toolset must be enabled with a non-read-only profile before implementation. New assets must use "
        "a logical folder and correct `parent_path` when that profile is active."
    )
    mutation_workflow = (
        "Core mutation workflows are active. Use the server's Resolve flow for collisions and honor cancellation or "
        "replacement decisions."
        if not read_only
        else "This is a read-only server profile. Diagnose and plan only; do not attempt project mutations."
    )
    delete_workflow = (
        "For any delete or cleanup candidate, first use `gm_safe_delete` with `dry_run=true` and honor its Resolve decision."
        if not read_only
        else "Deletion workflows are unavailable in this read-only profile; identify candidates without modifying them."
    )
    refactor_workflow = (
        "For asset renames use `gm_workflow_rename`; for copies use `gm_workflow_duplicate`. Let Resolve handle collisions."
        if not read_only
        else "Rename and duplicate tools are unavailable in this read-only profile. Produce a precise refactor plan and "
        "state that a non-read-only profile is required to apply it."
    )
    if read_only:
        bridge_workflow = (
            "Use `gm_capabilities` to confirm this read-only profile. Live run, stop, log, and bridge controls are not "
            "available; inspect only existing project assets and report what cannot be observed live."
        )
    elif "bridge" in enabled:
        bridge_workflow = (
            "The `bridge` toolset is active. Start with `gm_run_status` and `gm_bridge_status`, then use read-only bridge "
            "commands only after the bridge reports the game connected."
        )
    else:
        bridge_workflow = (
            "Start with `gm_capabilities` and `gm_run_status`. The `bridge` toolset is not active, so do not call "
            "`gm_bridge_*`; report that live state inspection requires enabling `bridge`."
        )
    index_workflow = (
        "Rebuild the symbol index with `gm_build_index` when names or references changed, then re-run targeted searches."
        if not read_only
        else "Do not rebuild indexes in this profile; use the available read-only asset and reference inspection tools."
    )
    verification_workflow = (
        "Compile with `gm_compile`, or use `gm_verification_flush` when pending mutation verification applies."
        if not read_only
        else "Do not compile or flush mutation verification in this profile; validate the plan with read-only diagnostics."
    )
    live_log_workflow = (
        "Read buffered observations with `gm_run_logs` after the bridge reports the game connected."
        if "bridge" in enabled and not read_only
        else "Live bridge logs are unavailable in this profile; do not attempt live log or command calls."
    )
    live_stop_workflow = (
        "Stop a session with `gm_run_stop` when it was started for this inspection, and verify status afterward."
        if not read_only
        else "Do not start or stop game sessions from this read-only profile."
    )
    fix_workflow = (
        "Make the smallest change that addresses the reported failure."
        if not read_only
        else "This profile is read-only: identify the smallest required change, but do not apply it. Report that a "
        "non-read-only profile is required for the fix/retry step."
    )
    feature_completion = (
        "After the focused implementation, inspect the resulting assets and run `gm_diagnostics`."
        if not read_only
        else "Finish by running read-only diagnostics and listing the exact changes a non-read-only profile must apply."
    )
    compile_retry_workflow = (
        "Compile again after each focused fix. Finish only after a successful compile, or clearly report the remaining "
        "compiler evidence and failed verification step."
        if not read_only
        else "Do not apply a fix or start a compile retry. Report the confirmed evidence, proposed smallest change, and "
        "the verification commands for a non-read-only profile."
    )
    compile_inspection = (
        "Confirm the target project with `gm_project_info`, then run `gm_compile` and preserve the actual error output."
        if not read_only
        else "Confirm the target project with `gm_project_info`, then inspect existing diagnostics and relevant assets; "
        "compile execution is unavailable in this profile."
    )
    live_setup_workflow = (
        "If live setup is genuinely needed, explain the mutation and use one-shot bridge setup only for the intended "
        "startup room and layer."
        if "bridge" in enabled and not read_only
        else "Do not install, enable, or alter bridge assets from this profile."
    )
    field_workflow = (
        "Initialize every required instance or struct field in Create, constructors, factories, or one-time normalization."
        if not read_only
        else "In the plan, place every required instance or struct field in Create, constructors, factories, or one-time "
        "normalization; do not edit those locations."
    )
    diagnose_remediation = (
        "If a focused fix is needed, preserve concrete up-front field initialization and verify the cause is gone with "
        "the same targeted diagnostics or compile evidence."
        if not read_only
        else "If a focused fix is needed, describe it without applying it and specify the later diagnostics or compile "
        "evidence needed to verify it."
    )
    diagnose_boundary = (
        "Keep inspection read-only until there is a specific remediation."
        if not read_only
        else "Keep the entire workflow read-only, including after a remediation is identified."
    )
    refactor_structure = (
        "Retain or establish concrete fields at creation/setup time. When creating replacement assets, first select or "
        "create the logical folder and set the correct `parent_path`; never put them at the `.yyp` root."
        if not read_only
        else "Plan concrete creation/setup fields and the intended logical folder and `parent_path` for any replacement "
        "asset, without creating or editing assets."
    )
    refactor_report = (
        "State exactly what was changed and what passed."
        if not read_only
        else "State exactly what is proposed, what evidence supports it, and which verification remains unavailable."
    )
    compile_structure = (
        "If the fix creates an asset, create or reuse a logical folder first and set its `parent_path` correctly."
        if not read_only
        else "If the proposed fix needs an asset, identify the logical folder and intended `parent_path` without creating it."
    )
    feature_report = (
        "Report the feature outcome and any verification that could not run."
        if not read_only
        else "Report the proposed feature outcome, supporting evidence, and every implementation/verification step still required."
    )

    @mcp.prompt(
        name="create-feature",
        title="Create a GameMaker feature",
        description=(
            "Plan, implement, and verify a scoped feature with safe asset organization."
            if not read_only
            else "Plan a scoped feature through read-only project inspection."
        ),
    )
    def create_feature() -> str:
        return f"""{feature_goal}

Start with `gm_capabilities`, `gm_project_info`, `gm_diagnostics`, and focused asset/code inspection. Reuse the nearest comparable asset and folder. {asset_workflow}

{mutation_workflow} {field_workflow} Do not add `*_exists(...)`, `variable_*_exists`, `struct_exists`, or lazy-default checks to Step, Draw, or other runtime paths.

{feature_completion} {verification_workflow} {feature_report}"""

    @mcp.prompt(
        name="diagnose-project",
        title="Diagnose a GameMaker project",
        description="Find the smallest evidence-backed cause before making any change.",
    )
    def diagnose_project() -> str:
        return f"""Diagnose the reported GameMaker problem before attempting a fix.

Establish the project with `gm_project_info`, then use `gm_diagnostics` at quick depth first. Use deep diagnostics, `gm_read_asset`, `gm_search_references`, `gm_get_asset_graph`, and symbol tools only where the first evidence points. Separate confirmed cause, missing evidence, and unrelated findings.

{diagnose_boundary} {delete_workflow} Do not replace a diagnosis with broad maintenance or destructive cleanup.

{diagnose_remediation} Never introduce GameMaker reflective `*_exists` probes."""

    @mcp.prompt(
        name="safe-refactor",
        title="Safely refactor GameMaker assets or code",
        description=(
            "Make a narrow refactor with reference checks, resolver decisions, and validation."
            if not read_only
            else "Plan a narrow refactor using read-only reference checks."
        ),
    )
    def safe_refactor() -> str:
        return f"""{refactor_goal}

Inspect the target using `gm_read_asset`, `gm_find_definition`, `gm_find_references`, or `gm_search_references` before editing. {refactor_workflow} {delete_workflow}

{refactor_structure} Do not add `*_exists(...)`, `variable_*_exists`, `struct_exists`, or hot-path lazy initialization.

{index_workflow} Then run `gm_diagnostics`. {verification_workflow} {refactor_report}"""

    @mcp.prompt(
        name="compile-fix-retry",
        title="Compile, fix, and retry",
        description=(
            "Turn a real compile failure into a focused fix-and-verify loop."
            if not read_only
            else "Diagnose compile evidence without running a build or editing the project."
        ),
    )
    def compile_fix_retry() -> str:
        return f"""{compile_goal}

{compile_inspection} Use `gm_diagnostics`, `gm_find_definition`, `gm_find_references`, and focused asset inspection to locate the cause; do not guess from a generic error label or run broad cleanup as a substitute for a fix.

{fix_workflow} Required instance and struct fields belong in Create, constructors, factories, or one-time normalization—not Step or Draw—and do not introduce any reflective `*_exists` checks. {compile_structure}

{compile_retry_workflow} {verification_workflow}"""

    @mcp.prompt(
        name="inspect-live-game",
        title="Inspect a live GameMaker game" if not read_only else "Assess live-game inspection readiness",
        description=(
            "Read a running game safely through the supported bridge protocol."
            if not read_only
            else "Assess available evidence without invoking live-game controls."
        ),
    )
    def inspect_live_game() -> str:
        return f"""{live_goal}

{bridge_workflow} {live_log_workflow} The bridge does not evaluate arbitrary GML, and ordinary debug output is not a bridge log unless the game emits `__mcp_log(...)`.

Do not change rooms, globals, or instances merely to inspect. {live_setup_workflow} Do not expose local paths, credentials, or other private host details in the result.

After inspection, report the observed game state separately from inferences. {live_stop_workflow}"""
