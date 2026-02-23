# GitHub Actions & Automation

This directory contains GitHub Actions workflows and automation scripts for gms-mcp.

## Tweet Automation

The `@gms_mcp` Twitter account is automated using Claude API to generate tweets 3x daily.

### How It Works

1. **Scheduled workflow** (`workflows/x-scheduled-post.yml`) runs at 8am, 2pm, 8pm UTC
2. **Tweet generation** (`scripts/generate_tweet.py`) calls Claude API with context
3. **Posting** (`scripts/post_tweet.py`) posts to X via API
4. **History tracking** persists across runs via GitHub Actions cache

### History Persistence

**Why we use cache instead of committing history:**

The `main` branch is protected and cannot be pushed to from GitHub Actions workflows. We use `actions/cache` with a static key (`tweet-history-v1`) to persist tweet history between runs.

Key points:
- Static cache key ensures the same entry is overwritten each run
- Cache is accessed 3x/day, so it won't expire (7-day limit is for non-accessed caches)
- History includes: posted tweets, topic/format/angle coverage tracking, hashtag metadata

**If history resets unexpectedly:**
1. Check if the workflow has been paused for >7 days (cache may have expired)
2. The system will reinitialize with empty coverage and rebuild naturally
3. For manual intervention, you can seed a `tweet_history.json` file in the workflow

### Content Diversity System

To prevent repetitive tweets, the system tracks and rotates:

1. **Topics** (14 categories): Code Intelligence, Asset Creation, Maintenance, etc.
2. **Formats** (6 styles): Problem/Solution, Scenario, Comparison, Tip, Q&A, Workflow Story
3. **Angles** (6+ per topic): Different perspectives on each topic
4. **Opening patterns** (7 types): Statement, Scenario, Discovery, Comparison, Question, Workflow, Tip
5. **Hashtag strategy**: Freeform, contextual hashtags (0-2 max, optional when not useful)

Each dimension is tracked independently with timestamps, ensuring the least-recently-used option is selected.

### Validation

Generated tweets are validated for:
- Length (50-280 characters)
- Hashtag count (max 2)
- Bad patterns (corporate speak, emoji spam, negative GameMaker framing)
- Exact duplicates (hash comparison)
- Semantic duplicates (>60% word overlap with recent tweets)
- Overused opening patterns

### Files

- `workflows/x-scheduled-post.yml` - Main workflow
- `workflows/x-evergreen-experiment.yml` - Evergreen experiment workflow
- `scripts/generate_tweet.py` - Tweet generation with Claude API
- `scripts/post_tweet.py` - X API posting
- `scripts/post_evergreen.py` - Evergreen queue posting (does not use `next_tweet.txt`)
- `scripts/report_evergreen_experiment.py` - Experiment KPI report generation
- `scripts/tweet_context.py` - Topic categories, formats, context building
- `x-personality.md` - Voice/tone guidelines

## Evergreen Experiment Controls

The evergreen experiment is controlled entirely through repository variables:

- `X_SCHEDULED_PAUSED` - when set to `true`, `x-scheduled-post.yml` is paused.
- `X_EVERGREEN_EXPERIMENT_ACTIVE` - when set to `true`, evergreen workflow can run.
- `X_EVERGREEN_EXPERIMENT_START_UTC` - ISO UTC experiment start timestamp.
- `X_EVERGREEN_EXPERIMENT_END_UTC` - ISO UTC experiment end timestamp (exclusive).
- `X_EVERGREEN_QUEUE_FILE` - optional queue file path (defaults to `.github/evergreen_queue.json`).

The evergreen workflow posts from a versioned queue file and records metrics
to job summary + artifacts without changing the release/main tweet staging flow.

## Other Workflows

- `release.yml` - Automated releases on version tags
- `test.yml` - CI testing on pull requests
