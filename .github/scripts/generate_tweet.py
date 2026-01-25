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
    TWEET_FORMATS,
    OPENING_PATTERNS,
    build_context_for_claude,
    get_personality_guide,
    initialize_angle_coverage,
    initialize_format_coverage,
    initialize_opening_coverage,
    initialize_topic_coverage,
    parse_changelog_released,
    select_angle,
    select_format,
    select_opening_pattern,
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
            "format_coverage": initialize_format_coverage(),
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
            if "format_coverage" not in data:
                data["format_coverage"] = initialize_format_coverage()
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
            "format_coverage": initialize_format_coverage(),
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


def compute_word_overlap(text1: str, text2: str) -> float:
    """Compute word overlap percentage between two texts."""
    # Normalize: lowercase, remove hashtags, split into words
    def normalize(text: str) -> set[str]:
        text = re.sub(r'#\w+', '', text.lower())  # Remove hashtags
        text = re.sub(r'[^\w\s]', ' ', text)  # Remove punctuation
        words = set(text.split())
        # Remove common stop words
        stop_words = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
                      'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                      'would', 'could', 'should', 'may', 'might', 'must', 'to',
                      'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'it',
                      'this', 'that', 'and', 'or', 'but', 'if', 'your', 'you'}
        return words - stop_words

    words1 = normalize(text1)
    words2 = normalize(text2)

    if not words1 or not words2:
        return 0.0

    overlap = len(words1 & words2)
    min_len = min(len(words1), len(words2))
    return overlap / min_len if min_len > 0 else 0.0


def is_semantic_duplicate(content: str, history: dict, threshold: float = 0.6) -> tuple[bool, str]:
    """Check if tweet content is semantically similar to recent tweets."""
    recent_tweets = history.get("posted", [])[-10:]  # Check last 10 tweets

    for tweet in recent_tweets:
        prev_content = tweet.get('content') or tweet.get('preview', '')
        if not prev_content:
            continue

        overlap = compute_word_overlap(content, prev_content)
        if overlap >= threshold:
            return True, f"semantic_duplicate ({overlap:.0%} overlap with recent tweet)"

    return False, ""


def validate_tweet(content: str, history: dict) -> tuple[bool, str]:
    """Validate generated tweet meets requirements."""
    content = content.strip()

    # Length checks
    if len(content) > MAX_TWEET_LENGTH:
        return False, f"too_long ({len(content)} chars)"

    if len(content) < MIN_TWEET_LENGTH:
        return False, f"too_short ({len(content)} chars)"

    # Exact duplicate check
    if is_duplicate(content, history):
        return False, "duplicate"

    # Semantic duplicate check (>60% word overlap with recent tweets)
    is_sem_dup, sem_reason = is_semantic_duplicate(content, history, threshold=0.6)
    if is_sem_dup:
        return False, sem_reason

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
        # Never be negative about GameMaker
        (r"gamemaker.{0,20}(painful|tedious|annoying|frustrating|slow|clunky)", "negative_gamemaker"),
        (r"(painful|tedious|annoying|frustrating).{0,20}(menu|click|ide)", "negative_gamemaker"),
        (r"nightmare", "negative_framing"),
    ]

    for pattern, reason in bad_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return False, f"bad_pattern: {reason}"

    # Overused opening patterns
    overused_openings = [
        (r"^your ai (can|now)", "your_ai_opener"),
        (r"^finally[,!]", "finally_opener"),
        (r"^no more ", "no_more_opener"),
        (r"^tired of ", "tired_of_opener"),
        (r"^just (describe|tell|ask)", "just_verb_opener"),
        (r"^ever (wanted|wished|needed)", "ever_wanted_opener"),
        (r"^imagine ", "imagine_opener"),
    ]

    for pattern, reason in overused_openings:
        if re.search(pattern, content, re.IGNORECASE):
            return False, f"overused_opening: {reason}"

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
- NEVER be negative about GameMaker itself - we complement it, we don't criticize it
- Frame benefits as "AI speeds this up" not "GameMaker is slow/tedious/painful"

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


def generate_tweet(history: dict, dry_run: bool = False) -> tuple[str, str, str, int, str]:
    """Generate a tweet using Claude API.

    Returns: (tweet_content, topic, format, angle_idx, opening_pattern)
    """
    # Select topic based on coverage
    topic_coverage = history.get("topic_coverage", initialize_topic_coverage())
    topic = select_topic(topic_coverage)
    print(f"Selected topic: {topic} ({TOPIC_CATEGORIES[topic]['name']})")

    # Select format based on coverage
    format_coverage = history.get("format_coverage", initialize_format_coverage())
    tweet_format = select_format(format_coverage)
    print(f"Selected format: {tweet_format} ({TWEET_FORMATS[tweet_format]['name']})")

    # Select angle based on coverage
    angle_coverage = history.get("angle_coverage", initialize_angle_coverage())
    angle_idx, selected_angle = select_angle(topic, angle_coverage)
    print(f"Selected angle: {angle_idx} - {selected_angle[:50]}...")

    # Select opening pattern based on coverage
    opening_coverage = history.get("opening_coverage", initialize_opening_coverage())
    opening_pattern = select_opening_pattern(opening_coverage)
    print(f"Selected opening pattern: {opening_pattern}")

    # Load context
    changelog = parse_changelog_released()
    recent_tweets = history.get("posted", [])[-15:]  # Expanded from 10 to 15

    context = build_context_for_claude(
        topic, tweet_format, selected_angle, recent_tweets, changelog,
        suggested_opening=opening_pattern
    )
    personality = get_personality_guide()

    system_prompt = build_system_prompt(personality)
    user_prompt = build_user_prompt(context, recent_tweets)

    print("Calling Claude API...")

    if dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        # Return a placeholder for dry-run without API key
        return f"[DRY RUN] Would generate tweet about {topic}", topic, tweet_format, angle_idx, opening_pattern

    # Generate with validation loop
    for attempt in range(3):
        tweet = call_claude_api(user_prompt, system_prompt)

        # Clean up response (remove quotes if present)
        tweet = tweet.strip().strip('"').strip("'")

        # Validate
        valid, reason = validate_tweet(tweet, history)
        if valid:
            print(f"Generated valid tweet ({len(tweet)} chars)")
            return tweet, topic, tweet_format, angle_idx, opening_pattern

        print(f"Attempt {attempt + 1}: Invalid tweet ({reason}), retrying...")

        # Add feedback for next attempt
        user_prompt += f"\n\nPrevious attempt was invalid: {reason}. Try again with a different approach."

    # If all attempts fail, return last attempt anyway
    print("Warning: Could not generate valid tweet after 3 attempts")
    return tweet, topic, tweet_format, angle_idx, opening_pattern


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
        tweet, topic, tweet_format, angle_idx, opening_pattern = generate_tweet(history, dry_run=args.dry_run)
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
    print(f"Format: {tweet_format}")
    print(f"Angle: {angle_idx}")
    print(f"Opening: {opening_pattern}")

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

    # Update topic and format coverage
    now = datetime.now(timezone.utc).isoformat()
    history["topic_coverage"][topic] = now
    if "format_coverage" not in history:
        history["format_coverage"] = initialize_format_coverage()
    history["format_coverage"][tweet_format] = now

    # Update angle coverage
    if "angle_coverage" not in history:
        history["angle_coverage"] = initialize_angle_coverage()
    if topic not in history["angle_coverage"]:
        history["angle_coverage"][topic] = {str(i): None for i in range(len(TOPIC_CATEGORIES[topic]["angles"]))}
    history["angle_coverage"][topic][str(angle_idx)] = now

    # Update opening pattern coverage
    if "opening_coverage" not in history:
        history["opening_coverage"] = initialize_opening_coverage()
    history["opening_coverage"][opening_pattern] = now

    save_history(history)
    set_github_output("tweet_generated", "true")
    set_github_output("topic", topic)
    set_github_output("format", tweet_format)

    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
