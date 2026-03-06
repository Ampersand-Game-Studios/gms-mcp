#!/usr/bin/env python3
"""
Post evergreen experiment tweets from a versioned queue.

This script is intentionally separate from post_tweet.py so evergreen posting
never touches .github/next_tweet.txt (release/main flow staging).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Keep imports local to the scripts folder for workflow execution.
import post_tweet

EXPERIMENT_GENERATED_BY = "evergreen-experiment"
QUEUE_DEFAULT = Path(".github/evergreen_queue.json")
POSTED_STATUSES = {"posted", "duplicate_on_x"}


def set_output(name: str, value: str) -> None:
    """Set GitHub Actions output variable."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def parse_iso_utc(value: str | None) -> datetime | None:
    """Parse ISO datetime into UTC."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_metric(text: str) -> int:
    """Parse compact numeric metrics like 1.2K."""
    raw = (text or "").strip().replace(",", "").replace(" ", "")
    if not raw:
        return 0
    mult = 1
    if raw[-1] in ("K", "k"):
        mult = 1_000
        raw = raw[:-1]
    elif raw[-1] in ("M", "m"):
        mult = 1_000_000
        raw = raw[:-1]
    elif raw[-1] in ("B", "b"):
        mult = 1_000_000_000
        raw = raw[:-1]
    try:
        return int(float(raw) * mult)
    except ValueError:
        return 0


def normalize_slot(slot: str) -> str:
    """Normalize slot to two-digit hour (UTC)."""
    val = int(slot)
    if val < 0 or val > 23:
        raise ValueError("slot must be 0-23")
    return f"{val:02d}"


def load_queue(queue_file: Path) -> dict[str, Any]:
    """Load evergreen queue JSON."""
    with open(queue_file, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_entry_timestamp(entry: dict[str, Any]) -> datetime | None:
    """Parse history entry timestamp safely."""
    timestamp = entry.get("timestamp")
    if not timestamp:
        return None
    try:
        return parse_iso_utc(timestamp)
    except ValueError:
        return None


def has_non_evergreen_post_today(history: dict[str, Any], day: datetime.date) -> bool:
    """Return True when any non-evergreen post already happened today (UTC)."""
    for entry in history.get("posted", []):
        ts = parse_entry_timestamp(entry)
        if ts is None or ts.date() != day:
            continue
        status = entry.get("status")
        generated_by = entry.get("generated_by")
        if status in POSTED_STATUSES and generated_by != EXPERIMENT_GENERATED_BY:
            return True
    return False


def has_evergreen_post_in_slot_today(history: dict[str, Any], day: datetime.date, slot: str) -> bool:
    """Return True when evergreen already posted in this UTC day+hour slot."""
    normalized_slot = normalize_slot(slot)
    for entry in history.get("posted", []):
        ts = parse_entry_timestamp(entry)
        if ts is None or ts.date() != day:
            continue
        status = entry.get("status")
        generated_by = entry.get("generated_by")
        if status not in POSTED_STATUSES or generated_by != EXPERIMENT_GENERATED_BY:
            continue
        if f"{ts.hour:02d}" == normalized_slot:
            return True
    return False


def usage_count(history: dict[str, Any], queue_id: str) -> int:
    """Count how many times a queue item has already been used."""
    count = 0
    for entry in history.get("posted", []):
        if entry.get("format") != queue_id:
            continue
        if entry.get("generated_by") != EXPERIMENT_GENERATED_BY:
            continue
        if entry.get("status") in POSTED_STATUSES:
            count += 1
    return count


def pick_queue_item(
    queue: dict[str, Any],
    slot: str,
    history: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """Select next eligible queue item for slot."""
    posts = queue.get("posts")
    if not isinstance(posts, list):
        return None, "invalid_queue_schema"

    any_active = False
    any_slot = False
    any_reusable = False

    for post in posts:
        if not isinstance(post, dict):
            continue
        if not post.get("active", True):
            continue
        any_active = True

        slots = post.get("slots", ["08", "14", "20"])
        normalized_slots: list[str] = []
        for value in slots:
            try:
                normalized_slots.append(normalize_slot(str(value)))
            except ValueError:
                continue
        if slot not in normalized_slots:
            continue
        any_slot = True

        queue_id = str(post.get("id", "")).strip()
        text = str(post.get("text", "")).strip()
        if not queue_id or not text:
            continue
        if len(text) > 280:
            continue

        max_uses = int(post.get("max_uses", 1))
        used = usage_count(history, queue_id)
        if used >= max_uses:
            continue

        # Static queue text cannot be reposted verbatim on X, so keep scanning.
        candidate_hash = post_tweet.compute_hash(text)
        if post_tweet.is_duplicate_in_history(history, candidate_hash):
            continue

        any_reusable = True
        return post, ""

    if not any_active:
        return None, "no_active_posts"
    if not any_slot:
        return None, "no_post_for_slot"
    if not any_reusable:
        return None, "queue_exhausted"
    return None, "no_eligible_post"


def post_to_x(tweet_text: str) -> tuple[bool, str, str | None]:
    """
    Post tweet text to X.

    Returns:
      (success, reason, tweet_id)
    """
    result = post_tweet.post_text_to_x(tweet_text)
    return result.ok, result.reason, result.tweet_id


def execute(args: argparse.Namespace) -> int:
    """Execute evergreen post attempt."""
    now = parse_iso_utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc)
    slot = normalize_slot(args.slot) if args.slot else f"{now.hour:02d}"
    set_output("slot", slot)

    start = parse_iso_utc(os.environ.get("X_EVERGREEN_EXPERIMENT_START_UTC"))
    end = parse_iso_utc(os.environ.get("X_EVERGREEN_EXPERIMENT_END_UTC"))

    if start and now < start:
        set_output("posted", "false")
        set_output("skip_reason", "outside_window_before_start")
        return 0
    if end and now >= end:
        set_output("posted", "false")
        set_output("skip_reason", "outside_window_after_end")
        return 0

    queue_file = Path(args.queue_file)
    if not queue_file.exists():
        set_output("posted", "false")
        set_output("skip_reason", "queue_missing")
        return 0

    history = post_tweet.load_history()
    if has_non_evergreen_post_today(history, now.date()):
        set_output("posted", "false")
        set_output("skip_reason", "collision_non_evergreen_today")
        return 0
    if has_evergreen_post_in_slot_today(history, now.date(), slot):
        set_output("posted", "false")
        set_output("skip_reason", "already_posted_slot_today")
        return 0

    try:
        queue = load_queue(queue_file)
    except (OSError, json.JSONDecodeError):
        set_output("posted", "false")
        set_output("skip_reason", "queue_invalid_json")
        return 0

    chosen, reason = pick_queue_item(queue, slot, history)
    if not chosen:
        set_output("posted", "false")
        set_output("skip_reason", reason or "no_eligible_post")
        return 0

    queue_id = str(chosen["id"]).strip()
    tweet_text = str(chosen["text"]).strip()
    tweet_hash = post_tweet.compute_hash(tweet_text)

    set_output("queue_id", queue_id)
    set_output("tweet_hash", tweet_hash)

    if post_tweet.is_duplicate_in_history(history, tweet_hash):
        set_output("posted", "false")
        set_output("skip_reason", "duplicate_history")
        return 0

    if args.dry_run:
        set_output("posted", "false")
        set_output("skip_reason", "dry_run")
        print(f"[DRY RUN] Queue item {queue_id}: {tweet_text}")
        return 0

    success, post_reason, tweet_id = post_to_x(tweet_text)
    if success:
        post_tweet.add_to_history(
            history,
            tweet_hash,
            tweet_text,
            "posted",
            tweet_id,
            "evergreen",
            queue_id,
            EXPERIMENT_GENERATED_BY,
        )
        post_tweet.save_history(history)
        set_output("posted", "true")
        set_output("skip_reason", "")
        set_output("tweet_id", str(tweet_id))
        print(f"Posted evergreen tweet {queue_id} ({tweet_id})")
        return 0

    if post_reason == "duplicate_on_x":
        post_tweet.add_to_history(
            history,
            tweet_hash,
            tweet_text,
            "duplicate_on_x",
            None,
            "evergreen",
            queue_id,
            EXPERIMENT_GENERATED_BY,
        )
        post_tweet.save_history(history)
        set_output("posted", "false")
        set_output("skip_reason", "duplicate_on_x")
        return 0

    set_output("posted", "false")
    set_output("skip_reason", post_reason)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Post evergreen experiment tweet")
    parser.add_argument(
        "--queue-file",
        default=str(QUEUE_DEFAULT),
        help="Path to evergreen queue JSON file",
    )
    parser.add_argument(
        "--slot",
        default="",
        help="UTC hour slot to select from queue (e.g. 08, 14, 20)",
    )
    parser.add_argument(
        "--now-utc",
        default="",
        help="Override current time in ISO UTC format (tests)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select candidate and emit outputs, but do not post",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return execute(args)
    except ValueError as exc:
        set_output("posted", "false")
        set_output("skip_reason", "invalid_input")
        print(f"Input error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
