from __future__ import annotations

from gms_mcp.telemetry import (
    clear_spool,
    count_spool_events,
    disable_telemetry,
    emit_consent_changed,
    enable_telemetry,
    flush_spool,
    resolve_state,
)


def handle_telemetry_enable(args) -> bool:
    include_install_hash = bool(getattr(args, "with_install_id", False))
    enable_telemetry(include_install_hash=include_install_hash)
    emit_consent_changed("enable")
    print("[OK] Telemetry enabled.")
    print(f"[INFO] Stable install hash: {'enabled' if include_install_hash else 'disabled'}")
    return True


def handle_telemetry_disable(args) -> bool:
    previous_state = resolve_state(getattr(args, "telemetry", "inherit"))
    if previous_state.enabled:
        emit_consent_changed("disable")
    disable_telemetry()
    print("[OK] Telemetry disabled.")
    return True


def handle_telemetry_status(args) -> bool:
    state = resolve_state(getattr(args, "telemetry", "inherit"))
    consent = "enabled" if state.enabled else ("disabled" if state.decision_made else "not-set")
    print(f"[INFO] Consent: {consent}")
    print(f"[INFO] Effective source: {state.source}")
    print(f"[INFO] Endpoint: {state.endpoint}")
    print(f"[INFO] Install hash enabled: {'yes' if state.include_install_hash else 'no'}")
    print(f"[INFO] Queued events: {count_spool_events()}")
    return True


def handle_telemetry_flush(args) -> bool:
    result = flush_spool(force=True)
    if result.ok:
        print(
            f"[OK] Flushed {result.sent_events} event(s) in {result.sent_batches} batch(es). "
            f"Remaining: {result.remaining_events}."
        )
        return True
    print(f"[WARN] {result.message} Remaining queued events: {result.remaining_events}.")
    return False


def handle_telemetry_clear(args) -> bool:
    removed = clear_spool()
    print(f"[OK] Cleared {removed} queued telemetry event(s).")
    return True
