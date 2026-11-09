from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from gms_mcp import telemetry as t


@pytest.fixture
def telemetry_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(t, "_test_env_enabled", lambda: False)
    for key in ("PYTEST_CURRENT_TEST", "GMS_TEST_SUITE", "CI", "GITHUB_ACTIONS", "GMS_MCP_TELEMETRY"):
        monkeypatch.delenv(key, raising=False)
    t.enable_telemetry()
    return tmp_path


def queue(**kwargs):
    return t.queue_event(
        state=t.resolve_state(),
        surface="cli",
        event_type="cli.command",
        action="asset.create",
        tool_name="asset.create",
        tool_family="asset",
        result="ok",
        **kwargs,
    )


def event():
    assert queue(duration_ms=10)
    return json.loads(next(t.telemetry_spool_dir().glob("*.ndjson")).read_text())


@pytest.mark.parametrize(
    "field,value",
    [
        ("extra", "secret"),
        ("tool_name", "/private/project"),
        ("interactive", "secret"),
        ("ci", True),
        ("test_env", True),
        ("schema_version", 2),
        ("session_id", "bad"),
        ("install_hash", "bad"),
        ("duration_ms", -1),
        ("timestamp", "invalid"),
        ("result", "invalid"),
    ],
)
def test_closed_schema_rejects_non_metadata(telemetry_home, field, value):
    payload = event()
    payload[field] = value
    assert not t._valid_spool_event(payload)


def test_disable_clears_spool_and_stale_state_or_force_cannot_reenable(telemetry_home):
    stale = t.resolve_state()
    assert queue()
    t.disable_telemetry()
    assert not list(t.telemetry_spool_dir().glob("*.ndjson"))
    assert not t.queue_event(
        state=stale,
        surface="cli",
        event_type="cli.command",
        action="test",
        tool_name="test",
        tool_family="test",
        result="ok",
        force=True,
    )
    with patch.object(t, "_post_batch") as upload:
        assert not t.flush_spool(force=True).ok
        upload.assert_not_called()


def test_identifier_withdrawal_redacts_pending_records_and_stale_state(telemetry_home):
    t.enable_telemetry(include_install_hash=True)
    stale = t.resolve_state()
    assert queue()
    t.enable_telemetry(include_install_hash=False)
    assert all("install_hash" not in json.loads(path.read_text()) for path in t.telemetry_spool_dir().glob("*.ndjson"))
    assert t.queue_event(
        state=stale,
        surface="cli",
        event_type="cli.command",
        action="asset.create",
        tool_name="asset.create",
        tool_family="asset",
        result="ok",
    )
    uploaded = []
    with patch.object(t, "_post_batch", side_effect=lambda endpoint, events: uploaded.extend(events)):
        assert t.flush_spool().sent_events == 2
    assert all("install_hash" not in record for record in uploaded)


def test_flush_rechecks_identifier_consent_for_existing_spool(telemetry_home):
    t.enable_telemetry(include_install_hash=True)
    assert queue()
    t.save_config(consent="enabled", include_install_hash=False, install_hash=None)
    uploaded = []
    with patch.object(t, "_post_batch", side_effect=lambda endpoint, events: uploaded.extend(events)):
        assert t.flush_spool().sent_events == 1
    assert "install_hash" not in uploaded[0]


@pytest.mark.parametrize("failure_stage", ["encode", "flush", "replace"])
def test_atomic_telemetry_failure_leaves_no_pending_files(telemetry_home, failure_stage):
    replacements = {
        "encode": patch.object(t.json, "dump", side_effect=OSError("injected encoding failure")),
        "flush": patch.object(t.os, "fsync", side_effect=OSError("injected flush failure")),
        "replace": patch.object(Path, "replace", side_effect=OSError("injected replace failure")),
    }
    with replacements[failure_stage]:
        assert not queue()
    assert list(t.telemetry_spool_dir().iterdir()) == []


def test_real_interrupted_queue_pending_record_is_recovered_on_disable(telemetry_home):
    t.enable_telemetry(include_install_hash=True)
    t.telemetry_spool_dir()
    script = """
import os,sys
from pathlib import Path
from unittest.mock import patch
from gms_mcp import telemetry as t
with patch.object(Path,'home',return_value=Path(sys.argv[1])),patch.object(t,'_test_env_enabled',return_value=False),patch.object(t,'_ci_enabled',return_value=False),patch.object(t.os,'fsync',side_effect=lambda _:os._exit(73)):
 t.queue_event(state=t.resolve_state(),surface='cli',event_type='cli.command',action='asset.create',tool_name='asset.create',tool_family='asset',result='ok')
"""
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    interrupted = subprocess.run([sys.executable, "-c", script, str(telemetry_home)], env=environment, timeout=10)
    assert interrupted.returncode == 73
    spool = t.telemetry_spool_dir()
    pending = list(spool.iterdir())
    assert len(pending) == 1
    assert "install_hash" in pending[0].read_text()
    unrelated = spool / "unrelated-user-file.txt"
    unrelated.write_text("keep")
    t.disable_telemetry()
    assert list(spool.iterdir()) == [unrelated]
    assert unrelated.read_text() == "keep"


def test_crash_pending_config_and_spool_are_recovered_without_following_links(telemetry_home, tmp_path):
    target = tmp_path / "private.txt"
    target.write_text("keep")
    pending_name = ".gms-mcp-telemetry-pending-" + "a" * 32 + "-owned.json"
    (t.telemetry_config_path().parent / pending_name).write_text("private install ID")
    spool = t.telemetry_spool_dir()
    (spool / pending_name).symlink_to(target)
    unrelated = spool / ".gms-mcp-telemetry-pending-unrelated.json"
    unrelated.write_text("keep too")
    t.disable_telemetry()
    assert not (t.telemetry_config_path().parent / pending_name).exists()
    assert not (spool / pending_name).exists()
    assert target.read_text() == "keep"
    assert unrelated.read_text() == "keep too"


def test_forcing_upload_never_bypasses_ci(telemetry_home, monkeypatch):
    assert queue()
    monkeypatch.setenv("CI", "true")
    with patch.object(t, "_post_batch") as upload:
        assert not t.flush_spool(force=True).ok
        upload.assert_not_called()
    assert not queue(force=True)


def test_retention_age_count_and_bytes_are_bounded(telemetry_home, monkeypatch):
    payload = event()
    spool = t.telemetry_spool_dir()
    payload["timestamp"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=8)).isoformat()
    (spool / "old.ndjson").write_text(json.dumps(payload))
    monkeypatch.setattr(t, "MAX_SPOOL_EVENTS", 3)
    for _ in range(6):
        assert queue()
    assert t.count_spool_events() == 3
    assert not (spool / "old.ndjson").exists()
    monkeypatch.setattr(t, "MAX_SPOOL_BYTES", 1)
    t.prune_spool()
    assert t.count_spool_events() == 0


def test_spool_symlink_removed_without_reading_or_deleting_target(telemetry_home, tmp_path):
    target = tmp_path / "private.txt"
    target.write_text("private data")
    link = t.telemetry_spool_dir() / "external.ndjson"
    link.symlink_to(target)
    assert t.prune_spool() == 1
    assert target.read_text() == "private data"


def test_symlink_spool_directory_never_writes_outside(telemetry_home, tmp_path):
    target = tmp_path / "external"
    target.mkdir()
    (t.telemetry_root() / t.SPOOL_SUBDIR).symlink_to(target)
    assert not queue()
    assert not list(target.iterdir())


def test_failed_upload_preserves_queue_for_retry(telemetry_home):
    assert queue()
    with patch.object(t, "_post_batch", side_effect=OSError("offline")):
        assert not t.flush_spool().ok
    assert t.count_spool_events() == 1
    with patch.object(t, "_post_batch"):
        assert t.flush_spool().sent_events == 1
    assert t.count_spool_events() == 0


def test_batch_count_and_actual_payload_bytes_are_bounded(telemetry_home, monkeypatch):
    for _ in range(5):
        assert queue()
    monkeypatch.setattr(t, "MAX_BATCH_BYTES", 1800)
    paths, records = t._load_spool_records(limit_events=2)
    assert 0 < len(records) <= 2
    assert len(paths) == len(records)
    body = json.dumps(
        {"schema_version": 1, "sent_at": t._utc_now_iso(), "events": records}, separators=(",", ":")
    ).encode()
    assert len(body) <= t.MAX_BATCH_BYTES


@pytest.mark.parametrize(
    "endpoint", ["http://example.com/events", "https://user:secret@example.com/events", "file:///private/events"]
)
def test_transport_rejects_plaintext_or_credentials_before_network(telemetry_home, endpoint):
    with patch("urllib.request.build_opener") as opener:
        with pytest.raises(ValueError):
            t._post_batch(endpoint, [event()])
        opener.assert_not_called()


def test_upload_redirects_fail_closed():
    request = t.urllib.request.Request("https://example.com/events")
    with pytest.raises(urllib.error.HTTPError):
        t._NoUploadRedirect().redirect_request(request, None, 302, "redirect", {}, "http://other.example/events")


def test_disable_waits_for_inflight_upload_and_no_later_batch_sends(telemetry_home):
    assert queue()
    started = threading.Event()
    release = threading.Event()
    disabled = threading.Event()

    def upload(*_):
        started.set()
        assert release.wait(5)

    def disable():
        t.disable_telemetry()
        disabled.set()

    with patch.object(t, "_post_batch", side_effect=upload):
        flushing = threading.Thread(target=t.flush_spool)
        flushing.start()
        assert started.wait(5)
        withdrawal = threading.Thread(target=disable)
        withdrawal.start()
        assert not disabled.wait(0.05)
        release.set()
        flushing.join(5)
        withdrawal.join(5)
    assert not flushing.is_alive() and not withdrawal.is_alive()
    assert disabled.is_set()
    assert t.count_spool_events() == 0
    assert not queue()


def test_client_schema_matches_ingest_service_schema():
    schema_path = Path(__file__).resolve().parents[3] / "services" / "telemetry" / "src" / "event-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["schema_version"] == t.SCHEMA_VERSION
    assert schema["fields"] == t.EVENT_FIELD_RULES
    assert schema["token_pattern"] == t.EVENT_TOKEN_PATTERN
    assert schema["event_surfaces"] == t.EVENT_SURFACES
    assert schema["results"] == list(t.EVENT_RESULTS)
    assert schema["error_families"] == list(t.EVENT_ERROR_FAMILIES)
    assert schema["duration_buckets"] == list(t.EVENT_DURATION_BUCKETS)
    assert schema["max_duration_ms"] == t.EVENT_MAX_DURATION_MS
    assert schema["max_event_age_ms"] == t.EVENT_MAX_AGE_MS
    assert schema["max_clock_skew_ms"] == t.EVENT_MAX_CLOCK_SKEW_MS
    assert schema["version_pattern"] == t.EVENT_VERSION_PATTERN
    assert schema["python_version_pattern"] == t.EVENT_PYTHON_VERSION_PATTERN
    assert schema["timestamp_pattern"] == t.EVENT_TIMESTAMP_PATTERN


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool_name", "x" * 65),
        ("tool_family", "x" * 33),
        ("event_type", "arbitrary"),
        ("event_type", "mcp.tool"),
        ("error_family", "secret"),
        ("duration_bucket", "secret"),
        ("duration_ms", 7 * 86400000 + 1),
        ("python_version", "private-value"),
        ("gms_mcp_version", "private-value"),
        ("timestamp", "2026-01-01T00:00:00+00:00"),
    ],
)
def test_client_rejects_what_the_service_would_reject(telemetry_home, field, value):
    payload = event()
    payload[field] = value
    assert not t._valid_spool_event(payload)


def test_queue_does_not_wait_for_inflight_upload(telemetry_home):
    assert queue()
    started = threading.Event()
    release = threading.Event()

    def upload(*_):
        started.set()
        assert release.wait(5)

    with patch.object(t, "_post_batch", side_effect=upload):
        flushing = threading.Thread(target=t.flush_spool)
        flushing.start()
        try:
            assert started.wait(5)
            began = time.monotonic()
            assert queue()
            assert time.monotonic() - began < 1
        finally:
            release.set()
            flushing.join(5)
    assert not flushing.is_alive()
    assert t.count_spool_events() == 0


def test_queue_gives_up_quickly_when_state_lock_is_busy(telemetry_home):
    holding = threading.Event()
    release = threading.Event()

    def hold():
        with t._state_guard():
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert holding.wait(5)
        began = time.monotonic()
        assert not queue()
        assert time.monotonic() - began < 2
    finally:
        release.set()
        holder.join(5)


@pytest.mark.parametrize("status,kept", [(400, 0), (413, 0), (429, 1), (408, 1), (503, 1)])
def test_permanent_client_rejection_drops_batch_but_retryable_keeps_it(telemetry_home, status, kept):
    assert queue()
    error = urllib.error.HTTPError("https://example.com", status, "rejected", {}, None)
    with patch.object(t, "_post_batch", side_effect=error):
        result = t.flush_spool()
    assert result.ok is (kept == 0)
    assert t.count_spool_events() == kept


def test_consent_event_honours_per_run_off(telemetry_home, monkeypatch):
    t.clear_spool()
    monkeypatch.setenv("GMS_MCP_TELEMETRY", "off")
    with patch.object(t, "maybe_start_background_flush") as flush:
        t.emit_consent_changed("enable")
    assert t.count_spool_events() == 0
    flush.assert_not_called()
    monkeypatch.delenv("GMS_MCP_TELEMETRY")
    with patch.object(t, "maybe_start_background_flush") as flush:
        t.emit_consent_changed("enable", cli_override="off")
    assert t.count_spool_events() == 0
    flush.assert_not_called()


def test_cli_override_reaches_background_flush_process(telemetry_home):
    t.save_config(consent=None, include_install_hash=False, install_hash=None)
    assert queue_with_state(t.resolve_state("on"))
    with patch.object(t.subprocess, "Popen") as popen:
        assert t.maybe_start_background_flush(force=True, cli_override="on")
    assert popen.call_args.kwargs["env"]["GMS_MCP_TELEMETRY"] == "on"


def queue_with_state(state):
    return t.queue_event(
        state=state,
        surface="cli",
        event_type="cli.command",
        action="asset.create",
        tool_name="asset.create",
        tool_family="asset",
        result="ok",
    )


def test_prompt_without_stdin_does_not_crash_or_record_a_decision(telemetry_home):
    t.save_config(consent=None, include_install_hash=False, install_hash=None)
    with patch("builtins.input", side_effect=EOFError):
        assert t.prompt_for_consent() is False
    assert t.load_config().consent is None


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, False),
        ({"CI": "false"}, False),
        ({"CI": "0"}, False),
        ({"CI": "true"}, True),
        ({"CI": "1"}, True),
        ({"GITHUB_ACTIONS": "true"}, True),
        ({"BUILD_BUILDID": "42"}, True),
        ({"JENKINS_URL": "https://ci.example"}, True),
    ],
)
def test_shared_ci_detection(env, expected):
    from gms_mcp.ci_detection import is_ci_environment

    assert is_ci_environment(env) is expected
