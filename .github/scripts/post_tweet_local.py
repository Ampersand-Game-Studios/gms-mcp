#!/usr/bin/env python3
"""
Local X/Twitter posting tool for testing.

Usage:
    python .github/scripts/post_tweet_local.py "Your tweet text here"
    python .github/scripts/post_tweet_local.py --file .github/next_tweet.txt
    python .github/scripts/post_tweet_local.py --dry-run "Test tweet"

Requires a .env file in the project root with:
    X_APP_KEY=...
    X_APP_SECRET=...
    X_ACCESS_TOKEN=...
    X_ACCESS_SECRET=...
"""

import argparse
import os
import sys
from pathlib import Path


def load_env():
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent.parent.parent / ".env"

    if not env_path.exists():
        print(f"Error: .env file not found at {env_path}")
        print("Copy .env.example to .env and fill in your X API credentials.")
        return False

    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

    return True


def validate_credentials():
    """Check that all required credentials are present."""
    required = ["X_APP_KEY", "X_APP_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
    missing = [key for key in required if not os.environ.get(key)]

    if missing:
        print(f"Error: Missing credentials in .env: {missing}")
        return False

    return True


def safe_print(text: str) -> None:
    """Print text safely, handling encoding issues on Windows."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Fall back to ASCII with replacement for problematic chars
        print(text.encode('ascii', errors='replace').decode('ascii'))


def post_tweet(text: str, dry_run: bool = False) -> bool:
    """Post a tweet to X."""
    text = text.strip()

    if not text:
        print("Error: Tweet text is empty")
        return False

    if len(text) > 280:
        print(f"Error: Tweet is {len(text)} chars (max 280)")
        return False

    print(f"Tweet ({len(text)} chars):")
    print("-" * 40)
    safe_print(text)
    print("-" * 40)

    if dry_run:
        print("\n[DRY RUN] Would post the above tweet.")
        return True

    try:
        import tweepy
    except ImportError:
        print("Error: tweepy not installed. Run: pip install tweepy")
        return False

    try:
        client = tweepy.Client(
            consumer_key=os.environ["X_APP_KEY"],
            consumer_secret=os.environ["X_APP_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_SECRET"],
        )

        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]

        print(f"\nSuccess! Tweet posted.")
        print(f"ID: {tweet_id}")
        print(f"URL: https://x.com/i/status/{tweet_id}")
        return True

    except Exception as e:
        print(f"\nError posting tweet: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Post to X/Twitter locally for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "text",
        nargs="?",
        help="Tweet text to post"
    )
    parser.add_argument(
        "--file", "-f",
        help="Read tweet text from file"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be posted without actually posting"
    )

    args = parser.parse_args()

    # Get tweet text
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: File not found: {args.file}")
            return 1
        text = file_path.read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        parser.print_help()
        return 1

    # Load credentials (not required for dry run)
    if not args.dry_run:
        if not load_env():
            return 1
        if not validate_credentials():
            return 1

    # Post
    success = post_tweet(text, dry_run=args.dry_run)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
