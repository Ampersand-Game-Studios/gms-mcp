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
import sys
from datetime import datetime, timezone
from pathlib import Path

# Constants
TWEET_FILE = Path(".github/next_tweet.txt")
HISTORY_FILE = Path(".github/tweet_history.json")
MAX_HISTORY_ENTRIES = 100  # Keep last N tweets to prevent file bloat


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of normalized tweet content."""
    normalized = content.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


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


def add_to_history(history: dict, tweet_hash: str, tweet_preview: str, status: str, tweet_id: str = None) -> None:
    """Add a tweet to the history."""
    entry = {
        "hash": tweet_hash,
        "preview": tweet_preview[:50] + "..." if len(tweet_preview) > 50 else tweet_preview,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if tweet_id:
        entry["tweet_id"] = tweet_id
    history["posted"].append(entry)


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

    try:
        import tweepy
    except ImportError:
        print("Error: tweepy not installed")
        return 1

    # Validate credentials
    required_env = ["X_APP_KEY", "X_APP_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
    missing = [key for key in required_env if not os.environ.get(key)]
    if missing:
        print(f"Error: Missing credentials: {missing}")
        return 1

    try:
        client = tweepy.Client(
            consumer_key=os.environ["X_APP_KEY"],
            consumer_secret=os.environ["X_APP_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_SECRET"],
        )

        response = client.create_tweet(text=tweet_content)
        tweet_id = response.data["id"]

        print(f"\n[SUCCESS]")
        print(f"Tweet posted! ID: {tweet_id}")
        print(f"URL: https://x.com/i/status/{tweet_id}")

        # Record success and clear file
        add_to_history(history, tweet_hash, tweet_content, "posted", tweet_id)
        save_history(history)
        clear_tweet_file()
        set_output("should_commit", "true")
        return 0

    except tweepy.Forbidden as e:
        error_str = str(e)
        print(f"\n[FORBIDDEN ERROR] {e}")

        # Check if it's a duplicate content error from X
        if "duplicate" in error_str.lower():
            print("\nX rejected this as duplicate content.")
            print("The tweet was likely already posted successfully.")
            print("Marking as posted and clearing file.")

            add_to_history(history, tweet_hash, tweet_content, "duplicate_on_x")
            save_history(history)
            clear_tweet_file()
            set_output("should_commit", "true")
            return 0

        # Other forbidden errors (permissions, etc.)
        print("This may be a permissions issue with the X API credentials.")
        return 1

    except tweepy.TooManyRequests as e:
        print(f"\n[RATE LIMITED] {e}")
        print("Too many requests. The tweet will be retried on the next push.")
        # Don't clear file - allow retry
        return 1

    except tweepy.TwitterServerError as e:
        print(f"\n[X SERVER ERROR] {e}")
        print("X's servers are having issues. Will retry on next push.")
        # Don't clear file - allow retry
        return 1

    except tweepy.Unauthorized as e:
        print(f"\n[UNAUTHORIZED] {e}")
        print("API credentials are invalid or expired.")
        print("Please check the X_* secrets in GitHub repository settings.")
        return 1

    except tweepy.BadRequest as e:
        print(f"\n[BAD REQUEST] {e}")
        print("The tweet content may be invalid (too long, forbidden content, etc.)")
        # Clear file to prevent repeated failures
        add_to_history(history, tweet_hash, tweet_content, "rejected_invalid")
        save_history(history)
        clear_tweet_file()
        set_output("should_commit", "true")
        return 1

    except Exception as e:
        print(f"\n[UNEXPECTED ERROR] {type(e).__name__}: {e}")
        print("An unexpected error occurred. Not clearing tweet file.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
