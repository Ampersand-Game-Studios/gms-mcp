from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]


def load_module(module_name: str, relative_path: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeTimeout(Exception):
    pass


class FakeRequestException(Exception):
    pass


class FakeResponse:
    def __init__(self, status_code: int, *, payload: dict | None = None, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.reason = text or f"HTTP {status_code}"

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_fake_requests():
    return SimpleNamespace(
        Timeout=FakeTimeout,
        RequestException=FakeRequestException,
        Session=lambda: FakeSession([]),
    )


def set_x_credentials(monkeypatch):
    monkeypatch.setenv("X_APP_KEY", "key")
    monkeypatch.setenv("X_APP_SECRET", "secret")
    monkeypatch.setenv("X_ACCESS_TOKEN", "token")
    monkeypatch.setenv("X_ACCESS_SECRET", "token-secret")


def fake_oauth_factory(*args, **kwargs):
    return {"args": args, "kwargs": kwargs}


def make_completed_process(returncode: int, *, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_post_text_to_x_retries_server_errors_then_succeeds(monkeypatch):
    module = load_module("test_post_tweet_retry_success", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    session = FakeSession(
        [
            FakeResponse(503, text="Service Unavailable"),
            FakeResponse(503, text="Service Unavailable"),
            FakeResponse(201, payload={"data": {"id": "tweet-123"}}),
        ]
    )
    sleeps: list[float] = []
    logs: list[str] = []

    result = module.post_text_to_x(
        "hello world",
        requests_module=make_fake_requests(),
        session=session,
        oauth_factory=fake_oauth_factory,
        max_attempts=4,
        sleep_func=sleeps.append,
        log_func=logs.append,
    )

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-123"
    assert len(session.calls) == 3
    assert session.calls[0]["url"] == module.X_POST_URL
    assert session.calls[0]["json"] == {"text": "hello world"}
    assert session.calls[0]["headers"]["Accept"] == "application/json"
    assert "gms-mcp-x-post/1.0" in session.calls[0]["headers"]["User-Agent"]
    assert session.calls[0]["timeout"] == module.REQUEST_TIMEOUT_SECONDS
    assert sleeps == [5, 15]
    assert any("Retrying in 5s" in line for line in logs)


def test_post_text_to_x_exhausts_server_error_retries(monkeypatch):
    module = load_module("test_post_tweet_retry_failure", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    session = FakeSession([FakeResponse(503, text="Service Unavailable")] * 4)
    sleeps: list[float] = []
    monkeypatch.setattr(module, "post_text_to_x_with_xurl", lambda *args, **kwargs: module.XPostResult(False, "xurl_unavailable"))

    result = module.post_text_to_x(
        "hello world",
        requests_module=make_fake_requests(),
        session=session,
        oauth_factory=fake_oauth_factory,
        max_attempts=2,
        sleep_func=sleeps.append,
        log_func=lambda _: None,
    )

    assert result.ok is False
    assert result.reason == "x_server_error"
    assert result.tweet_id is None
    assert len(session.calls) == 2
    assert session.calls[0]["url"] == module.X_POST_URL
    assert sleeps == [5]


def test_post_text_to_x_uses_xurl_fallback_after_v2_failures(monkeypatch):
    module = load_module("test_post_tweet_xurl_fallback", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    session = FakeSession(
        [
            FakeResponse(503, text="Service Unavailable"),
            FakeResponse(503, text="Service Unavailable"),
        ]
    )
    sleeps: list[float] = []
    logs: list[str] = []
    monkeypatch.setattr(
        module,
        "post_text_to_x_with_xurl",
        lambda *args, **kwargs: module.XPostResult(True, "posted", "tweet-xurl"),
    )

    result = module.post_text_to_x(
        "hello world",
        requests_module=make_fake_requests(),
        session=session,
        oauth_factory=fake_oauth_factory,
        max_attempts=2,
        sleep_func=sleeps.append,
        log_func=logs.append,
    )

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-xurl"
    assert [call["url"] for call in session.calls] == [module.X_POST_URL, module.X_POST_URL]
    assert sleeps == [5]
    assert any("XURL FALLBACK" in line for line in logs)


def test_post_text_to_x_with_xurl_posts_successfully(monkeypatch):
    module = load_module("test_post_tweet_xurl_success", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    monkeypatch.setattr(module, "resolve_xurl_bin", lambda: "/fake/xurl")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["auth", "oauth1"]:
            return make_completed_process(0, stdout="saved")
        if command[1:2] == ["post"]:
            return make_completed_process(0, stdout=json.dumps({"data": {"id": "tweet-via-xurl"}}))
        raise AssertionError(f"unexpected command: {command}")

    result = module.post_text_to_x_with_xurl("hello world", run_command=fake_run, log_func=lambda _: None)

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-via-xurl"
    assert commands[0][0] == "/fake/xurl"
    assert commands[1] == ["/fake/xurl", "post", "hello world", "--auth", "oauth1"]


def test_post_text_to_x_with_xurl_returns_forbidden(monkeypatch):
    module = load_module("test_post_tweet_xurl_forbidden", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    monkeypatch.setattr(module, "resolve_xurl_bin", lambda: "/fake/xurl")

    def fake_run(command, **kwargs):
        if command[1:3] == ["auth", "oauth1"]:
            return make_completed_process(0, stdout="saved")
        return make_completed_process(
            1,
            stdout=json.dumps(
                {
                    "title": "Forbidden",
                    "status": 403,
                    "detail": "You currently have access to a subset of X API V2 endpoints only.",
                }
            ),
        )

    result = module.post_text_to_x_with_xurl("hello world", run_command=fake_run, log_func=lambda _: None)

    assert result.ok is False
    assert result.reason == "forbidden"


def test_post_text_to_x_ignores_long_retry_after_on_server_errors(monkeypatch):
    module = load_module("test_post_tweet_retry_after_ignored", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    session = FakeSession(
        [
            FakeResponse(503, text="Service Unavailable", headers={"retry-after": "436"}),
            FakeResponse(201, payload={"data": {"id": "tweet-789"}}),
        ]
    )
    sleeps: list[float] = []

    result = module.post_text_to_x(
        "hello world",
        requests_module=make_fake_requests(),
        session=session,
        oauth_factory=fake_oauth_factory,
        max_attempts=4,
        sleep_func=sleeps.append,
        log_func=lambda _: None,
    )

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-789"
    assert sleeps == [5]


def test_post_text_to_x_caps_retry_after_on_rate_limit(monkeypatch):
    module = load_module("test_post_tweet_retry_after_capped", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    session = FakeSession(
        [
            FakeResponse(429, text="Too Many Requests", headers={"retry-after": "436"}),
            FakeResponse(201, payload={"data": {"id": "tweet-999"}}),
        ]
    )
    sleeps: list[float] = []

    result = module.post_text_to_x(
        "hello world",
        requests_module=make_fake_requests(),
        session=session,
        oauth_factory=fake_oauth_factory,
        max_attempts=4,
        sleep_func=sleeps.append,
        log_func=lambda _: None,
    )

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-999"
    assert sleeps == [module.MAX_RETRY_HINT_SECONDS]


def test_post_text_to_x_retries_edge_challenge(monkeypatch):
    module = load_module("test_post_tweet_edge_challenge", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    session = FakeSession(
        [
            FakeResponse(
                403,
                text="<!DOCTYPE html><title>Just a moment...</title><script>window._cf_chl_opt = {};</script>",
            ),
            FakeResponse(201, payload={"data": {"id": "tweet-edge"}}),
        ]
    )
    sleeps: list[float] = []

    result = module.post_text_to_x(
        "hello world",
        requests_module=make_fake_requests(),
        session=session,
        oauth_factory=fake_oauth_factory,
        max_attempts=4,
        sleep_func=sleeps.append,
        log_func=lambda _: None,
    )

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-edge"
    assert sleeps == [5]


def test_post_text_to_x_retries_network_timeout(monkeypatch):
    module = load_module("test_post_tweet_network_timeout", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    session = FakeSession(
        [
            FakeTimeout("read timed out"),
            FakeResponse(201, payload={"data": {"id": "tweet-456"}}),
        ]
    )
    sleeps: list[float] = []

    result = module.post_text_to_x(
        "hello world",
        requests_module=make_fake_requests(),
        session=session,
        oauth_factory=fake_oauth_factory,
        max_attempts=3,
        sleep_func=sleeps.append,
        log_func=lambda _: None,
    )

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-456"
    assert sleeps == [5]


def test_deferred_history_does_not_block_future_retries(monkeypatch):
    module = load_module("test_post_tweet_deferred_history", ".github/scripts/post_tweet.py")
    history = {
        "posted": [
            {
                "hash": "abc123",
                "status": module.DEFERRED_STATUS,
            }
        ]
    }

    assert module.is_duplicate_in_history(history, "abc123") is False


def test_transient_failure_reason_helper():
    module = load_module("test_post_tweet_transient_reason_helper", ".github/scripts/post_tweet.py")

    assert module.is_transient_x_failure("x_server_error") is True
    assert module.is_transient_x_failure("x_edge_challenge") is True
    assert module.is_transient_x_failure("bad_request") is False


def test_x_post_workflow_supports_manual_dispatch():
    workflow_text = (REPO_ROOT / ".github/workflows/x-post.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow_text


def test_x_workflows_define_timeout_guards():
    workflow_paths = [
        ".github/workflows/x-post.yml",
        ".github/workflows/x-scheduled-post.yml",
        ".github/workflows/x-evergreen-experiment.yml",
    ]

    for relative_path in workflow_paths:
        workflow_text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "timeout-minutes:" in workflow_text


def test_x_workflows_install_direct_http_dependencies():
    workflow_paths = [
        ".github/workflows/x-post.yml",
        ".github/workflows/x-scheduled-post.yml",
        ".github/workflows/x-evergreen-experiment.yml",
    ]

    for relative_path in workflow_paths:
        workflow_text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "requests-oauthlib" in workflow_text


def test_x_post_workflow_commits_cleared_staging_file():
    workflow_text = (REPO_ROOT / ".github/workflows/x-post.yml").read_text(encoding="utf-8")

    assert "contents: write" in workflow_text
    assert "steps.post.outputs.should_commit == 'true'" in workflow_text
    assert "git add .github/next_tweet.txt" in workflow_text
    assert "Reset staged release tweet [skip ci]" in workflow_text
    assert "git push origin HEAD:main" in workflow_text
