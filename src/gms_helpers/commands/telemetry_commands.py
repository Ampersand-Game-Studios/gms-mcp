from __future__ import annotations

from ..results import OperationResult
from gms_mcp.telemetry import (
    clear_spool,
    count_spool_events,
    disable_telemetry,
    emit_consent_changed,
    enable_telemetry,
    flush_spool,
    resolve_state,
)


def handle_telemetry_enable(args) -> OperationResult:
    include_install_hash = bool(getattr(args, "with_install_id", False))
    enable_telemetry(include_install_hash=include_install_hash)
    emit_consent_changed("enable")
    print("[OK] Telemetry enabled.")
    print(f"[INFO] Stable install hash: {'enabled' if include_install_hash else 'disabled'}")
    return OperationResult.ok(
        "Telemetry enabled",
        data={"include_install_hash": include_install_hash},
    )


def handle_telemetry_disable(args) -> OperationResult:
    previous_state = resolve_state(getattr(args, "telemetry", "inherit"))
    if previous_state.enabled:
        emit_consent_changed("disable")
    disable_telemetry()
    print("[OK] Telemetry disabled.")
    return OperationResult.ok("Telemetry disabled", data={"previously_enabled": previous_state.enabled})


def handle_telemetry_status(args) -> OperationResult:
    state = resolve_state(getattr(args, "telemetry", "inherit"))
    consent = "enabled" if state.enabled else ("disabled" if state.decision_made else "not-set")
    queued_events = count_spool_events()
    print(f"[INFO] Consent: {consent}")
    print(f"[INFO] Effective source: {state.source}")
    print(f"[INFO] Endpoint: {state.endpoint}")
    print(f"[INFO] Install hash enabled: {'yes' if state.include_install_hash else 'no'}")
    print(f"[INFO] Queued events: {queued_events}")
    return OperationResult.ok(
        "Telemetry status read",
        data={
            "consent": consent,
            "source": state.source,
            "endpoint": state.endpoint,
            "include_install_hash": state.include_install_hash,
            "queued_events": queued_events,
        },
    )


def handle_telemetry_flush(args) -> OperationResult:
    result = flush_spool(force=True)
    data = {
        "sent_events": result.sent_events,
        "sent_batches": result.sent_batches,
        "remaining_events": result.remaining_events,
    }
    if result.ok:
        print(
            f"[OK] Flushed {result.sent_events} event(s) in {result.sent_batches} batch(es). "
            f"Remaining: {result.remaining_events}."
        )
        return OperationResult.ok(result.message, data=data)
    print(f"[WARN] {result.message} Remaining queued events: {result.remaining_events}.")
    return OperationResult.fail(
        result.message,
        code="telemetry_flush_failed",
        error_type="telemetry_error",
        details=data,
        data=data,
    )


def handle_telemetry_clear(args) -> OperationResult:
    removed = clear_spool()
    print(f"[OK] Cleared {removed} queued telemetry event(s).")
    return OperationResult.ok("Telemetry queue cleared", data={"removed": removed})
