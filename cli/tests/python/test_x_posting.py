from __future__ import annotations

import importlib.util
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


class FakeTwitterServerError(Exception):
    pass


class FakeTooManyRequests(Exception):
    pass


class FakeForbidden(Exception):
    pass


class FakeUnauthorized(Exception):
    pass


class FakeBadRequest(Exception):
    pass


class FakeClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def create_tweet(self, *, text: str):
        self.calls.append(text)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(data={"id": outcome})


def make_fake_tweepy(outcomes):
    client = FakeClient(outcomes)
    fake_tweepy = SimpleNamespace(
        Client=lambda **_: client,
        TwitterServerError=FakeTwitterServerError,
        TooManyRequests=FakeTooManyRequests,
        Forbidden=FakeForbidden,
        Unauthorized=FakeUnauthorized,
        BadRequest=FakeBadRequest,
    )
    return fake_tweepy, client


def set_x_credentials(monkeypatch):
    monkeypatch.setenv("X_APP_KEY", "key")
    monkeypatch.setenv("X_APP_SECRET", "secret")
    monkeypatch.setenv("X_ACCESS_TOKEN", "token")
    monkeypatch.setenv("X_ACCESS_SECRET", "token-secret")


def test_post_text_to_x_retries_server_errors_then_succeeds(monkeypatch):
    module = load_module("test_post_tweet_retry_success", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    fake_tweepy, client = make_fake_tweepy(
        [FakeTwitterServerError("503"), FakeTwitterServerError("503"), "tweet-123"]
    )
    sleeps: list[float] = []
    logs: list[str] = []

    result = module.post_text_to_x(
        "hello world",
        tweepy_module=fake_tweepy,
        max_attempts=4,
        sleep_func=sleeps.append,
        log_func=logs.append,
    )

    assert result.ok is True
    assert result.reason == "posted"
    assert result.tweet_id == "tweet-123"
    assert client.calls == ["hello world", "hello world", "hello world"]
    assert sleeps == [5, 15]
    assert any("Retrying in 5s" in line for line in logs)


def test_post_text_to_x_exhausts_server_error_retries(monkeypatch):
    module = load_module("test_post_tweet_retry_failure", ".github/scripts/post_tweet.py")
    set_x_credentials(monkeypatch)
    fake_tweepy, client = make_fake_tweepy([FakeTwitterServerError("503")] * 4)
    sleeps: list[float] = []

    result = module.post_text_to_x(
        "hello world",
        tweepy_module=fake_tweepy,
        max_attempts=4,
        sleep_func=sleeps.append,
        log_func=lambda _: None,
    )

    assert result.ok is False
    assert result.reason == "x_server_error"
    assert result.tweet_id is None
    assert client.calls == ["hello world"] * 4
    assert sleeps == [5, 15, 30]


def test_x_post_workflow_supports_manual_dispatch():
    workflow_text = (REPO_ROOT / ".github/workflows/x-post.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow_text
