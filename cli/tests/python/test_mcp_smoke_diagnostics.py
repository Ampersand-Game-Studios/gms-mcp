"""Smoke failure summaries must retain causes without leaking credentials."""

import asyncio
import json

import pytest

from scripts.run_mcp_tool_smoke import MCPToolSmokeRunner, ToolRunRecord, _error_text, _is_ok


def test_nested_worker_failure_keeps_error_and_both_streams():
    result = {
        "ok": False,
        "message": "Tool failed",
        "error": {"message": "Transaction failed", "details": {"cause": "journal fingerprint mismatch"}},
        "result": {"success": False, "message": "Object registration failed"},
        "stderr": "PermissionError: Windows access denied",
        "stdout": "Created objects/o_test/o_test.yy",
    }
    summary = _error_text(result)
    for expected in [
        "Transaction failed",
        "journal fingerprint mismatch",
        "Object registration failed",
        "PermissionError: Windows access denied",
        "Created objects/o_test/o_test.yy",
    ]:
        assert expected in summary


def test_diagnostic_fields_redact_credentials_and_never_dump_payload():
    result = {
        "ok": False,
        "error": {"message": "Access denied", "details": {"api_key": "key-secret", "password": "pw-secret"}},
        "authorization": "auth-secret",
        "credentials": {"message": "nested-secret"},
        "stderr": "Authorization: Bearer bearer-secret\ntoken=token-secret password=pw-secret",
        "stdout": "command --api-key key-secret https://user:pw-secret@example.test/path",
    }
    summary = _error_text(result)
    assert "Access denied" in summary
    assert "[REDACTED]" in summary
    for secret in ["key-secret", "pw-secret", "auth-secret", "nested-secret", "bearer-secret", "token-secret"]:
        assert secret not in summary


def test_failure_without_diagnostics_has_safe_fallback():
    assert _error_text({"ok": False, "secret": "do-not-print"}) == "Operation failed (no diagnostic text returned)."


def test_repeated_diagnostics_are_deduplicated():
    summary = _error_text({"error": "same failure", "result": {"message": "same failure"}})
    assert summary.count("same failure") == 1


def test_diagnostics_are_bounded_without_losing_terminal_exception():
    summary = _error_text({"stderr": "prefix\n" + "x" * 24000 + "\nPermissionError: denied"})
    assert len(summary) <= 12000
    assert "PermissionError: denied" in summary
    assert "truncated" in summary


@pytest.mark.parametrize("result", [{"status": "failed"}, {"success": False}, {"ok": True, "errors": ["failed"]}])
def test_smoke_does_not_count_typed_failure_as_success(result):
    assert not _is_ok(result)


def test_report_redacts_nested_diagnostics_and_secret_fields(tmp_path):
    runner = MCPToolSmokeRunner(tmp_path / "base", tmp_path / "work", tmp_path / "report.json")
    runner.tools = ["gm_create_object"]
    runner.records = [
        ToolRunRecord(
            tool="gm_create_object",
            workspace="project",
            ok=False,
            args={"name": "o_test", "token": "argument-secret"},
            elapsed_seconds=0,
            result={
                "ok": False,
                "password": "result-secret",
                "access_key": "access-secret",
                "stderr": "token=stream-secret",
                "command": ["tool", "--api-key", "argv-secret", "--password=inline-secret"],
            },
            error="password=error-secret",
        )
    ]
    runner._write_report(runner.tools)
    report_text = runner.output_path.read_text()
    for secret in [
        "argument-secret",
        "result-secret",
        "stream-secret",
        "error-secret",
        "access-secret",
        "argv-secret",
        "inline-secret",
    ]:
        assert secret not in report_text
    report = json.loads(report_text)
    assert report["fail_count"] == 1
    assert report["results"][0]["args"]["name"] == "o_test"


def test_unknown_metadata_scalar_lists_are_not_failure_diagnostics():
    summary = _error_text({"error": "failed", "argv": ["--api-key", "not-a-diagnostic-secret"]})
    assert "failed" in summary
    assert "not-a-diagnostic-secret" not in summary


def test_uninitialized_smoke_server_reports_a_meaningful_failure(tmp_path):
    runner = MCPToolSmokeRunner(tmp_path / "base", tmp_path / "work", tmp_path / "report.json")
    with pytest.raises(RuntimeError, match="Smoke server has not been initialized"):
        asyncio.run(runner._call_tool("gm_project_info", {}))
