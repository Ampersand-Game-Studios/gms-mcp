## Contributing

### Branch flow
- Open PRs against `dev`
- Maintainers promote changes `dev` -> `pre-release` -> `main`

### Commit & PR summaries
When creating PRs to `main`, include a **Release post** section in the PR description if a post will be published:

```markdown
## Summary
- Brief description of changes

## Release post
> Your project, your rules. gms-mcp now supports custom naming conventions...

## Test plan
- [ ] Tests pass
```

This keeps the proposed X post visible during release review.

### X posting
X posting is handled by Codex/browser automation during release promotion, not by GitHub Actions or the X API.

- Personality / voice guide: `.github/x-personality.md`

**Publishing a post:**
1. Draft the post from the released changes, following `.github/x-personality.md`
2. Verify Chrome is logged into `@gms_mcp`
3. Use X's web UI to publish the post
4. Verify the post appears on the `@gms_mcp` profile and record the URL in the release closeout

**Skipping the post:**
To release without posting to X, state that explicitly in the release closeout.
