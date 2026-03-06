#!/usr/bin/env python3
"""
Robust Twitter/X posting script with duplicate detection and error handling.

Features:
- Hash-based duplicate detection using local history
- Graceful handling of X's duplicate content errors
- Atomic file operations
- Detailed logging
"""

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Constants
TWEET_FILE = Path(".github/next_tweet.txt")
HISTORY_FILE = Path(".github/tweet_history.json")
MAX_HISTORY_ENTRIES = 100  # Keep last N tweets to prevent file bloat
RETRY_BACKOFF_SECONDS = (5, 15, 30)
REQUEST_TIMEOUT_SECONDS = (10, 30)
MAX_RETRY_HINT_SECONDS = 30
X_POST_URL = "https://api.twitter.com/2/tweets"


@dataclass(frozen=True)
class XPostResult:
    """Result of an X post attempt."""

    ok: bool
    reason: str
    tweet_id: str | None = None


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of normalized tweet content."""
    normalized = content.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def extract_tools_mentioned(content: str) -> list[str]:
    """Extract gm_* tool names from tweet content."""
    return re.findall(r'\bgm_\w+\b', content)


def extract_hashtags_mentioned(content: str) -> list[str]:
    """Extract hashtags from tweet content."""
    return re.findall(r"(?<!\w)#\w+", content)


def load_history() -> dict:
    """Load tweet history from JSON file."""
    if not HISTORY_FILE.exists():
        return {"posted": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load history file: {e}")
        return {"posted": []}


def save_history(history: dict) -> None:
    """Save tweet history to JSON file, keeping only recent entries."""
    # Trim to max entries
    if len(history["posted"]) > MAX_HISTORY_ENTRIES:
        history["posted"] = history["posted"][-MAX_HISTORY_ENTRIES:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def add_to_history(
    history: dict,
    tweet_hash: str,
    tweet_content: str,
    status: str,
    tweet_id: str = None,
    topic: str = None,
    tweet_format: str = None,
    generated_by: str = "manual",
) -> None:
    """Add a tweet to the history."""
    entry = {
        "hash": tweet_hash,
        "content": tweet_content,  # Full content for deduplication
        "preview": tweet_content[:50] + "..." if len(tweet_content) > 50 else tweet_content,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "format": tweet_format,
        "generated_by": generated_by,
        "tools_mentioned": extract_tools_mentioned(tweet_content),
        "hashtags_mentioned": extract_hashtags_mentioned(tweet_content),
    }
    if tweet_id:
        entry["tweet_id"] = tweet_id
    history["posted"].append(entry)

    # Update generation stats if present
    if "generation_stats" in history and status == "posted":
        history["generation_stats"]["total_posted"] = history["generation_stats"].get("total_posted", 0) + 1


def is_duplicate_in_history(history: dict, tweet_hash: str) -> bool:
    """Check if a tweet hash already exists in history."""
    return any(entry["hash"] == tweet_hash for entry in history.get("posted", []))


def clear_tweet_file() -> None:
    """Clear the tweet file (empty it)."""
    with open(TWEET_FILE, "w", encoding="utf-8") as f:
        f.write("")


def set_output(name: str, value: str) -> None:
    """Set GitHub Actions output variable."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{name}={value}\n")


def default_log(message: str) -> None:
    """Print workflow logs immediately."""
    print(message, flush=True)


def create_x_auth(oauth_factory):
    """Build OAuth1 auth from environment credentials."""
    return oauth_factory(
        os.environ["X_APP_KEY"],
        os.environ["X_APP_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_SECRET"],
    )


def retry_delay_seconds(
    headers: dict | None,
    attempt: int,
    *,
    allow_retry_after: bool = False,
    allow_rate_limit_reset: bool = False,
) -> int:
    """Choose a retry delay, only honoring bounded API hints when explicitly allowed."""
    delay = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
    headers = headers or {}

    if allow_retry_after:
        retry_after = headers.get("retry-after")
        if retry_after:
            try:
                hinted_delay = max(1, int(float(retry_after)))
                return min(hinted_delay, MAX_RETRY_HINT_SECONDS)
            except (TypeError, ValueError):
                pass

    if allow_rate_limit_reset:
        rate_limit_reset = headers.get("x-rate-limit-reset")
        if rate_limit_reset:
            try:
                reset_epoch = int(float(rate_limit_reset))
                remaining = max(1, reset_epoch - int(time.time()))
                return min(remaining, MAX_RETRY_HINT_SECONDS)
            except (TypeError, ValueError):
                pass

    return delay


def response_error_text(response) -> str:
    """Extract a short error description from an API response."""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        parts: list[str] = []
        title = payload.get("title")
        detail = payload.get("detail")
        if title:
            parts.append(str(title))
        if detail:
            parts.append(str(detail))

        errors = payload.get("errors")
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict):
                    message = error.get("message") or error.get("detail")
                    if message:
                        parts.append(str(message))

        if parts:
            return " | ".join(parts)

    text = getattr(response, "text", "") or ""
    reason = getattr(response, "reason", "") or ""
    return text.strip() or reason or f"HTTP {getattr(response, 'status_code', 'unknown')}"


def post_text_to_x(
    tweet_content: str,
    *,
    requests_module=None,
    session=None,
    oauth_factory=None,
    max_attempts: int | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
    log_func: Callable[[str], None] | None = None,
) -> XPostResult:
    """Post a tweet with retry handling for transient X API failures."""
    logger = log_func or default_log
    if requests_module is None:
        try:
            import requests as requests_module
        except ImportError:
            logger("Error: requests not installed")
            return XPostResult(False, "missing_requests")
    if oauth_factory is None:
        try:
            from requests_oauthlib import OAuth1 as oauth_factory
        except ImportError:
            logger("Error: requests-oauthlib not installed")
            return XPostResult(False, "missing_oauth")

    required_env = ["X_APP_KEY", "X_APP_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
    missing = [key for key in required_env if not os.environ.get(key)]
    if missing:
        logger(f"Error: Missing credentials: {missing}")
        return XPostResult(False, "missing_credentials")

    http_session = session or requests_module.Session()
    auth = create_x_auth(oauth_factory)
    total_attempts = max_attempts or (len(RETRY_BACKOFF_SECONDS) + 1)

    for attempt in range(1, total_attempts + 1):
        if total_attempts > 1:
            logger(f"Post attempt {attempt}/{total_attempts}...")

        try:
            response = http_session.post(
                X_POST_URL,
                json={"text": tweet_content},
                auth=auth,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests_module.Timeout as exc:
            logger(f"\n[NETWORK TIMEOUT] {exc}")
            if attempt < total_attempts:
                delay = retry_delay_seconds({}, attempt)
                logger(f"Retrying in {delay}s (attempt {attempt + 1}/{total_attempts})...")
                sleep_func(delay)
                continue
            logger("X did not respond before the request timeout. The tweet will remain queued.")
            return XPostResult(False, "network_timeout")
        except requests_module.RequestException as exc:
            logger(f"\n[NETWORK ERROR] {exc}")
            if attempt < total_attempts:
                delay = retry_delay_seconds({}, attempt)
                logger(f"Retrying in {delay}s (attempt {attempt + 1}/{total_attempts})...")
                sleep_func(delay)
                continue
            logger("X could not be reached after retries. The tweet will remain queued.")
            return XPostResult(False, "network_error")

        error_text = response_error_text(response)
        status_code = getattr(response, "status_code", 0)
        headers = getattr(response, "headers", None) or {}

        if status_code in (200, 201):
            try:
                payload = response.json()
            except ValueError:
                logger("\n[UNEXPECTED ERROR] X returned invalid JSON for a successful post.")
                return XPostResult(False, "unexpected_error")

            tweet_id = str((payload.get("data") or {}).get("id") or "").strip()
            if not tweet_id:
                logger("\n[UNEXPECTED ERROR] X did not return a tweet ID.")
                return XPostResult(False, "unexpected_error")
            return XPostResult(True, "posted", tweet_id)

        if status_code == 403 and "duplicate" in error_text.lower():
            logger(f"\n[DUPLICATE ON X] {error_text}")
            return XPostResult(False, "duplicate_on_x")

        if status_code == 429:
            logger(f"\n[RATE LIMITED] {error_text}")
            if attempt < total_attempts:
                delay = retry_delay_seconds(
                    headers,
                    attempt,
                    allow_retry_after=True,
                    allow_rate_limit_reset=True,
                )
                logger(f"Retrying in {delay}s (attempt {attempt + 1}/{total_attempts})...")
                sleep_func(delay)
                continue
            logger("Too many requests. The tweet will be retried on the next workflow run.")
            return XPostResult(False, "rate_limited")

        if status_code >= 500:
            logger(f"\n[X SERVER ERROR] HTTP {status_code}: {error_text}")
            if attempt < total_attempts:
                delay = retry_delay_seconds(headers, attempt)
                logger(f"Retrying in {delay}s (attempt {attempt + 1}/{total_attempts})...")
                sleep_func(delay)
                continue
            logger("X's servers are still having issues after retries. The tweet will remain queued.")
            return XPostResult(False, "x_server_error")

        if status_code == 401:
            logger(f"\n[UNAUTHORIZED] {error_text}")
            logger("API credentials are invalid or expired.")
            logger("Please check the X_* secrets in GitHub repository settings.")
            return XPostResult(False, "unauthorized")

        if status_code == 400:
            logger(f"\n[BAD REQUEST] {error_text}")
            logger("The tweet content may be invalid (too long, forbidden content, etc.)")
            return XPostResult(False, "bad_request")

        if status_code == 403:
            logger(f"\n[FORBIDDEN ERROR] {error_text}")
            logger("This may be a permissions issue with the X API credentials.")
            return XPostResult(False, "forbidden")

        logger(f"\n[UNEXPECTED ERROR] HTTP {status_code}: {error_text}")
        logger("An unexpected error occurred. Not clearing tweet file.")
        return XPostResult(False, "unexpected_error")

    return XPostResult(False, "unexpected_error")


def main() -> int:
    print("=" * 50)
    print("X/Twitter Post Script")
    print("=" * 50)

    # Check if tweet file exists
    if not TWEET_FILE.exists():
        print(f"No tweet file found at {TWEET_FILE}")
        print("Nothing to post.")
        return 0

    # Read tweet content
    tweet_content = TWEET_FILE.read_text(encoding="utf-8").strip()

    # Skip if empty or whitespace only
    if not tweet_content:
        print("Tweet file is empty - nothing to post.")
        return 0

    print(f"Tweet content found ({len(tweet_content)} chars)")
    print(f"Preview: {tweet_content[:80]}...")

    # Get optional metadata from environment (set by generate_tweet.py)
    topic = os.environ.get("TWEET_TOPIC")
    tweet_format = os.environ.get("TWEET_FORMAT")
    generated_by = os.environ.get("TWEET_GENERATED_BY", "manual")

    # Compute hash for duplicate detection
    tweet_hash = compute_hash(tweet_content)
    print(f"Tweet hash: {tweet_hash}")

    # Load history and check for duplicates
    history = load_history()

    if is_duplicate_in_history(history, tweet_hash):
        print("\n[DUPLICATE DETECTED]")
        print("This tweet (or a very similar one) was already posted.")
        print("Clearing tweet file to prevent future retries.")
        clear_tweet_file()
        set_output("should_commit", "true")
        return 0

    # Attempt to post to X
    print("\nAttempting to post to X...")
    result = post_text_to_x(tweet_content)

    if result.ok:
        tweet_id = result.tweet_id
        print(f"\n[SUCCESS]")
        print(f"Tweet posted! ID: {tweet_id}")
        print(f"URL: https://x.com/i/status/{tweet_id}")

        # Record success and clear file
        add_to_history(history, tweet_hash, tweet_content, "posted", tweet_id, topic, tweet_format, generated_by)
        save_history(history)
        clear_tweet_file()
        set_output("should_commit", "true")
        return 0

    if result.reason == "duplicate_on_x":
        print("\nX rejected this as duplicate content.")
        print("The tweet was likely already posted successfully.")
        print("Marking as posted and clearing file.")

        add_to_history(history, tweet_hash, tweet_content, "duplicate_on_x", None, topic, tweet_format, generated_by)
        save_history(history)
        clear_tweet_file()
        set_output("should_commit", "true")
        return 0

    if result.reason == "bad_request":
        add_to_history(history, tweet_hash, tweet_content, "rejected_invalid", None, topic, tweet_format, generated_by)
        save_history(history)
        clear_tweet_file()
        set_output("should_commit", "true")
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
