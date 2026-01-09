## Contributing

### Branch flow
- Open PRs against `dev`
- Maintainers promote changes `dev` -> `pre-release` -> `main`

### Commit & PR summaries
When creating PRs to `main`, include a **Tweet** section in the PR description if a tweet will be posted:

```markdown
## Summary
- Brief description of changes

## Tweet
> Your project, your rules. gms-mcp now supports custom naming conventions...

## Test plan
- [ ] Tests pass
```

This helps reviewers see exactly what will be posted to X when the PR merges.

### X posting
When changes are promoted to `main`, a GitHub Action may post to X.

- Personality / voice guide: `.github/x-personality.md`
- Tweet staging file: `.github/next_tweet.txt`

**Preparing a tweet:**
1. Update `.github/next_tweet.txt` with the tweet content
2. Include the tweet in the PR description (see above)
3. The action posts automatically when the PR merges to `main`

**Skipping the tweet:**
To merge without posting to X, ensure `.github/next_tweet.txt` is empty.

The workflow safely handles:
- Empty file → skips posting
- Duplicate content → detects via hash and skips
- X API errors → appropriate retry or skip behavior
