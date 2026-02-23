#!/usr/bin/env python3
"""
Build evergreen experiment metrics and success verdict.

Outputs:
- JSON report
- CSV per-tweet metrics
- GitHub job summary markdown
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_metric(text: str) -> int:
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


def load_history(history_file: Path) -> dict[str, Any]:
    if not history_file.exists():
        return {"posted": []}
    with open(history_file, "r", encoding="utf-8") as fh:
        return json.load(fh)


def extract_metrics_from_html(html: str) -> dict[str, int] | None:
    """
    Extract first tweet metric row from a twstalker status page.

    Returns replies/retweets/likes/views/bookmarks/quotes/engagement.
    """
    pattern = re.compile(
        r"fa-comment.*?<span><ins></ins>\s*([^<]+)</span>"
        r".*?fa-retweet.*?<span><ins></ins>\s*([^<]+)</span>"
        r".*?fa-heart.*?<span><ins></ins>\s*([^<]+)</span>"
        r".*?fa-chart-simple.*?<span><ins></ins>\s*([^<]+)</span>"
        r".*?fa-bookmark.*?<span><ins></ins>\s*([^<]+)</span>",
        re.S,
    )
    match = pattern.search(html)
    if not match:
        return None

    replies, retweets, likes, views, bookmarks = (parse_metric(v) for v in match.groups())
    quotes = 0  # twstalker page does not expose quote count in this block
    engagement = replies + retweets + likes + quotes

    return {
        "replies": replies,
        "retweets": retweets,
        "likes": likes,
        "quotes": quotes,
        "views": views,
        "bookmarks": bookmarks,
        "engagement": engagement,
    }


def fetch_metrics(tweet_id: str) -> tuple[dict[str, int] | None, str | None]:
    url = f"https://twstalker.com/gms_mcp/status/{tweet_id}"
    cmd = ["curl", "-sS", "--max-time", "30", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None, f"curl_failed:{result.returncode}"

    metrics = extract_metrics_from_html(result.stdout)
    if metrics is None:
        return None, "metrics_not_found"
    return metrics, None


def entry_dt(entry: dict[str, Any]) -> datetime | None:
    try:
        return parse_iso_utc(entry.get("timestamp"))
    except ValueError:
        return None


def cohort_tweet_ids(
    history: dict[str, Any],
    *,
    generated_by: str,
    start: datetime,
    end: datetime,
) -> list[str]:
    ids: list[str] = []
    for entry in history.get("posted", []):
        if entry.get("generated_by") != generated_by:
            continue
        if entry.get("status") not in {"posted", "duplicate_on_x"}:
            continue
        dt = entry_dt(entry)
        if dt is None:
            continue
        if not (start <= dt < end):
            continue
        tweet_id = entry.get("tweet_id")
        if not tweet_id:
            continue
        ids.append(str(tweet_id))

    # Preserve order but dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for tid in ids:
        if tid in seen:
            continue
        seen.add(tid)
        ordered.append(tid)
    return ordered


@dataclass
class Aggregate:
    count: int
    fetched_count: int
    failed_count: int
    total_views: int
    total_engagement: int
    avg_views: float
    engagement_rate: float


def aggregate_metrics(rows: list[dict[str, Any]]) -> Aggregate:
    fetched = [row for row in rows if row.get("fetch_error") is None]
    total_views = sum(row["views"] for row in fetched)
    total_engagement = sum(row["engagement"] for row in fetched)
    fetched_count = len(fetched)
    count = len(rows)
    failed_count = count - fetched_count
    avg_views = (total_views / fetched_count) if fetched_count else 0.0
    engagement_rate = (total_engagement / total_views) if total_views else 0.0
    return Aggregate(
        count=count,
        fetched_count=fetched_count,
        failed_count=failed_count,
        total_views=total_views,
        total_engagement=total_engagement,
        avg_views=avg_views,
        engagement_rate=engagement_rate,
    )


def evaluate_success(
    baseline: Aggregate,
    experiment: Aggregate,
    *,
    min_views_uplift: float,
    max_er_drop: float,
) -> dict[str, Any]:
    """
    Evaluate success gate:
    - avg views uplift >= min_views_uplift
    - engagement rate drop <= max_er_drop
    """
    if baseline.fetched_count == 0 or baseline.avg_views <= 0 or baseline.total_views <= 0:
        return {
            "verdict": "inconclusive_no_baseline",
            "success": False,
            "views_uplift": None,
            "er_change": None,
            "pass_views_gate": False,
            "pass_er_gate": False,
        }
    if experiment.fetched_count == 0 or experiment.total_views <= 0:
        return {
            "verdict": "inconclusive_no_experiment_data",
            "success": False,
            "views_uplift": None,
            "er_change": None,
            "pass_views_gate": False,
            "pass_er_gate": False,
        }

    views_uplift = (experiment.avg_views / baseline.avg_views) - 1.0
    er_change = (experiment.engagement_rate / baseline.engagement_rate) - 1.0 if baseline.engagement_rate > 0 else 0.0
    pass_views_gate = views_uplift >= min_views_uplift
    pass_er_gate = er_change >= -max_er_drop
    success = pass_views_gate and pass_er_gate
    return {
        "verdict": "passed" if success else "failed",
        "success": success,
        "views_uplift": views_uplift,
        "er_change": er_change,
        "pass_views_gate": pass_views_gate,
        "pass_er_gate": pass_er_gate,
    }


def render_summary(
    *,
    now: datetime,
    baseline_window_start: datetime,
    baseline_window_end: datetime,
    experiment_window_start: datetime,
    experiment_window_end: datetime,
    baseline: Aggregate,
    experiment: Aggregate,
    verdict: dict[str, Any],
    min_views_uplift: float,
    max_er_drop: float,
) -> str:
    def pct(value: float | None) -> str:
        if value is None:
            return "n/a"
        return f"{value * 100:.2f}%"

    lines = [
        "## Evergreen Experiment Report",
        "",
        f"- Generated at: `{now.isoformat()}`",
        f"- Baseline window (claude-api): `{baseline_window_start.isoformat()}` to `{baseline_window_end.isoformat()}`",
        f"- Experiment window (evergreen): `{experiment_window_start.isoformat()}` to `{experiment_window_end.isoformat()}`",
        f"- Success gate: views uplift >= `{min_views_uplift * 100:.1f}%` and ER drop <= `{max_er_drop * 100:.1f}%`",
        "",
        "| Cohort | Posts (total/fetched) | Avg Views | Total Engagement | Engagement Rate |",
        "|---|---:|---:|---:|---:|",
        f"| Baseline | {baseline.count}/{baseline.fetched_count} | {baseline.avg_views:.2f} | {baseline.total_engagement} | {baseline.engagement_rate:.4f} |",
        f"| Experiment | {experiment.count}/{experiment.fetched_count} | {experiment.avg_views:.2f} | {experiment.total_engagement} | {experiment.engagement_rate:.4f} |",
        "",
        f"- Verdict: **{verdict['verdict']}**",
        f"- Views uplift: `{pct(verdict['views_uplift'])}` (pass: `{verdict['pass_views_gate']}`)",
        f"- ER change: `{pct(verdict['er_change'])}` (pass: `{verdict['pass_er_gate']}`)",
        "",
    ]
    return "\n".join(lines)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "cohort",
        "tweet_id",
        "views",
        "engagement",
        "likes",
        "retweets",
        "replies",
        "quotes",
        "bookmarks",
        "fetch_error",
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report evergreen experiment metrics")
    parser.add_argument("--history-file", default=".github/tweet_history.json")
    parser.add_argument("--start-utc", default="")
    parser.add_argument("--end-utc", default="")
    parser.add_argument("--baseline-days", type=int, default=14)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--now-utc", default="")
    parser.add_argument("--min-views-uplift", type=float, default=0.15)
    parser.add_argument("--max-er-drop", type=float, default=0.10)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    now = parse_iso_utc(args.now_utc) if args.now_utc else datetime.now(timezone.utc)
    start = parse_iso_utc(args.start_utc or os.environ.get("X_EVERGREEN_EXPERIMENT_START_UTC"))
    end = parse_iso_utc(args.end_utc or os.environ.get("X_EVERGREEN_EXPERIMENT_END_UTC"))
    if not start or not end:
        print("Missing experiment window start/end", file=sys.stderr)
        return 1

    history = load_history(Path(args.history_file))
    baseline_start = start - timedelta(days=args.baseline_days)
    baseline_end = start
    experiment_end = min(now, end)

    baseline_ids = cohort_tweet_ids(
        history,
        generated_by="claude-api",
        start=baseline_start,
        end=baseline_end,
    )
    experiment_ids = cohort_tweet_ids(
        history,
        generated_by="evergreen-experiment",
        start=start,
        end=experiment_end,
    )

    csv_rows: list[dict[str, Any]] = []
    for cohort, ids in (("baseline", baseline_ids), ("experiment", experiment_ids)):
        for tweet_id in ids:
            metrics, error = fetch_metrics(tweet_id)
            row = {
                "cohort": cohort,
                "tweet_id": tweet_id,
                "fetch_error": error,
                "views": 0,
                "engagement": 0,
                "likes": 0,
                "retweets": 0,
                "replies": 0,
                "quotes": 0,
                "bookmarks": 0,
            }
            if metrics:
                row.update(metrics)
            csv_rows.append(row)

    baseline_agg = aggregate_metrics([row for row in csv_rows if row["cohort"] == "baseline"])
    experiment_agg = aggregate_metrics([row for row in csv_rows if row["cohort"] == "experiment"])

    verdict = evaluate_success(
        baseline_agg,
        experiment_agg,
        min_views_uplift=args.min_views_uplift,
        max_er_drop=args.max_er_drop,
    )

    report = {
        "generated_at_utc": now.isoformat(),
        "baseline_window_start_utc": baseline_start.isoformat(),
        "baseline_window_end_utc": baseline_end.isoformat(),
        "experiment_window_start_utc": start.isoformat(),
        "experiment_window_end_utc": experiment_end.isoformat(),
        "baseline": baseline_agg.__dict__,
        "experiment": experiment_agg.__dict__,
        "verdict": verdict,
    }

    summary = render_summary(
        now=now,
        baseline_window_start=baseline_start,
        baseline_window_end=baseline_end,
        experiment_window_start=start,
        experiment_window_end=experiment_end,
        baseline=baseline_agg,
        experiment=experiment_agg,
        verdict=verdict,
        min_views_uplift=args.min_views_uplift,
        max_er_drop=args.max_er_drop,
    )

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    if args.output_csv:
        write_csv(csv_rows, Path(args.output_csv))

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write(summary)
            fh.write("\n")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
