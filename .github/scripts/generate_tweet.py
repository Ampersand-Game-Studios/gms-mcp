#!/usr/bin/env python3
"""
Automated tweet generation using Claude API.

Usage:
    python .github/scripts/generate_tweet.py           # Generate and write to next_tweet.txt
    python .github/scripts/generate_tweet.py --dry-run # Preview without writing

Requires ANTHROPIC_API_KEY environment variable (or in .env file for local testing).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def load_env_file():
    """Load environment variables from .env file if it exists (for local testing)."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() not in os.environ:  # Don't override existing env vars
                        os.environ[key.strip()] = value.strip()


# Load .env for local testing
load_env_file()

# Add scripts directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from tweet_context import (
    TOPIC_CATEGORIES,
    build_context_for_claude,
    get_personality_guide,
    initialize_topic_coverage,
    parse_changelog_released,
    select_topic,
)

# File paths
SCRIPT_DIR = Path(__file__).parent
GITHUB_DIR = SCRIPT_DIR.parent
TWEET_FILE = GITHUB_DIR / "next_tweet.txt"
HISTORY_FILE = GITHUB_DIR / "tweet_history.json"

# Generation constants
MAX_RETRIES = 3
MAX_TWEET_LENGTH = 280
MIN_TWEET_LENGTH = 50


def load_history() -> dict:
    """Load tweet history from JSON file."""
    if not HISTORY_FILE.exists():
        return {
            "posted": [],
            "topic_coverage": initialize_topic_coverage(),
            "generation_stats": {
                "total_generated": 0,
                "total_posted": 0,
                "failures": 0,
                "last_generation": None,
            },
        }
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Ensure all required fields exist
            if "topic_coverage" not in data:
                data["topic_coverage"] = initialize_topic_coverage()
            if "generation_stats" not in data:
                data["generation_stats"] = {
                    "total_generated": 0,
                    "total_posted": 0,
                    "failures": 0,
                    "last_generation": None,
                }
            return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load history: {e}")
        return {
            "posted": [],
            "topic_coverage": initialize_topic_coverage(),
            "generation_stats": {"total_generated": 0, "total_posted": 0, "failures": 0, "last_generation": None},
        }


def save_history(history: dict) -> None:
    """Save tweet history to JSON file."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def compute_hash(content: str) -> str:
    """Compute hash of normalized tweet content."""
    normalized = content.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def is_duplicate(content: str, history: dict) -> bool:
    """Check if tweet content is a duplicate."""
    content_hash = compute_hash(content)
    return any(entry.get("hash") == content_hash for entry in history.get("posted", []))


def validate_tweet(content: str, history: dict) -> tuple[bool, str]:
    """Validate generated tweet meets requirements."""
    content = content.strip()

    # Length checks
    if len(content) > MAX_TWEET_LENGTH:
        return False, f"too_long ({len(content)} chars)"

    if len(content) < MIN_TWEET_LENGTH:
        return False, f"too_short ({len(content)} chars)"

    # Duplicate check
    if is_duplicate(content, history):
        return False, "duplicate"

    # Hashtag count (max 3)
    hashtag_count = content.count("#")
    if hashtag_count > 3:
        return False, f"too_many_hashtags ({hashtag_count})"

    # Bad patterns to avoid
    bad_patterns = [
        (r"we are pleased", "corporate_speak"),
        (r"excited to announce", "corporate_speak"),
        (r"🚀🔥", "emoji_spam"),
        (r"💯", "emoji_spam"),
        (r"HUGE UPDATE", "all_caps_hype"),
        (r"synergy", "corporate_speak"),
        (r"leverage", "corporate_speak"),
        (r"game.?changer", "hyperbole"),
    ]

    for pattern, reason in bad_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return False, f"bad_pattern: {reason}"

    return True, "valid"


def call_claude_api(prompt: str, system_prompt: str) -> str:
    """Call Claude API with retries."""
    try:
        import anthropic
    except ImportError:
        print("Error: anthropic package not installed. Run: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()

        except anthropic.RateLimitError:
            if attempt < MAX_RETRIES - 1:
                wait_time = (2 ** attempt) * 10
                print(f"Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise

        except anthropic.APIError as e:
            print(f"Claude API error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)
                continue
            raise

    return ""


def build_system_prompt(personality: str) -> str:
    """Build the system prompt for Claude."""
    return f"""You are a tweet writer for gms-mcp, a GameMaker tooling project.

{personality}

CRITICAL CONSTRAINTS:
- Maximum 280 characters total (this is enforced)
- Maximum 2 hashtags
- Must be about RELEASED features only
- Lead with user benefit ("You can now X" not "We implemented Y")
- No corporate speak, no emoji spam
- Be specific about what the tool does

OUTPUT FORMAT:
Return ONLY the tweet text. No quotes, no explanations, no "Here's a tweet:" prefix.
Just the raw tweet content that will be posted directly."""


def build_user_prompt(context: str, recent_tweets: list[dict]) -> str:
    """Build the user prompt for Claude."""
    recent_text = "\n".join(
        f"- {t.get('preview', '')}" for t in recent_tweets[-5:]
    ) if recent_tweets else "None yet"

    return f"""Generate ONE tweet for gms-mcp.

{context}

RECENT TWEETS TO AVOID REPEATING:
{recent_text}

Requirements:
1. Highlight a specific tool or feature from the topic category
2. Be distinctly different from recent tweets
3. Include 1-2 relevant hashtags at the end
4. Keep it under 280 characters
5. Make it interesting and specific, not generic

Generate the tweet now:"""


def generate_tweet(history: dict, dry_run: bool = False) -> tuple[str, str]:
    """Generate a tweet using Claude API.

    Returns: (tweet_content, topic)
    """
    # Select topic based on coverage
    topic_coverage = history.get("topic_coverage", initialize_topic_coverage())
    topic = select_topic(topic_coverage)
    print(f"Selected topic: {topic} ({TOPIC_CATEGORIES[topic]['name']})")

    # Load context
    changelog = parse_changelog_released()
    recent_tweets = history.get("posted", [])[-10:]

    context = build_context_for_claude(topic, recent_tweets, changelog)
    personality = get_personality_guide()

    system_prompt = build_system_prompt(personality)
    user_prompt = build_user_prompt(context, recent_tweets)

    print("Calling Claude API...")

    if dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        # Return a placeholder for dry-run without API key
        return f"[DRY RUN] Would generate tweet about {topic}", topic

    # Generate with validation loop
    for attempt in range(3):
        tweet = call_claude_api(user_prompt, system_prompt)

        # Clean up response (remove quotes if present)
        tweet = tweet.strip().strip('"').strip("'")

        # Validate
        valid, reason = validate_tweet(tweet, history)
        if valid:
            print(f"Generated valid tweet ({len(tweet)} chars)")
            return tweet, topic

        print(f"Attempt {attempt + 1}: Invalid tweet ({reason}), retrying...")

        # Add feedback for next attempt
        user_prompt += f"\n\nPrevious attempt was invalid: {reason}. Try again with a different approach."

    # If all attempts fail, return last attempt anyway
    print("Warning: Could not generate valid tweet after 3 attempts")
    return tweet, topic


def set_github_output(name: str, value: str) -> None:
    """Set GitHub Actions output variable."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{name}={value}\n")


def main():
    parser = argparse.ArgumentParser(description="Generate tweet using Claude API")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview without writing to file")
    args = parser.parse_args()

    print("=" * 50)
    print("Tweet Generation Script")
    print("=" * 50)

    # Load history
    history = load_history()
    print(f"Loaded history: {len(history.get('posted', []))} previous tweets")

    # Generate tweet
    try:
        tweet, topic = generate_tweet(history, dry_run=args.dry_run)
    except Exception as e:
        print(f"Generation failed: {e}")
        history["generation_stats"]["failures"] = history["generation_stats"].get("failures", 0) + 1
        save_history(history)
        set_github_output("tweet_generated", "false")
        return 1

    # Display result
    print("\n" + "=" * 50)
    print(f"Generated Tweet ({len(tweet)} chars):")
    print("-" * 50)
    print(tweet)
    print("-" * 50)
    print(f"Topic: {topic}")

    if args.dry_run:
        print("\n[DRY RUN] Would write to next_tweet.txt")
        return 0

    # Write to file
    with open(TWEET_FILE, "w", encoding="utf-8") as f:
        f.write(tweet)
    print(f"\nWritten to {TWEET_FILE}")

    # Update history stats
    history["generation_stats"]["total_generated"] = history["generation_stats"].get("total_generated", 0) + 1
    history["generation_stats"]["last_generation"] = datetime.now(timezone.utc).isoformat()

    # Update topic coverage
    history["topic_coverage"][topic] = datetime.now(timezone.utc).isoformat()

    save_history(history)
    set_github_output("tweet_generated", "true")
    set_github_output("topic", topic)

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
