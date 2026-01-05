## Contributing

### Branch flow
- Open PRs against `dev`
- Maintainers promote changes `dev` -> `pre-release` -> `main`

### X posting
When changes are promoted to `main`, a GitHub Action may post to X.

- Personality / voice guide: `.github/x-personality.md`
- Tweet staging file: `.github/next_tweet.txt`

Maintainers prepare the tweet by updating `.github/next_tweet.txt` during the `pre-release` -> `main` PR.
If the staging file is unchanged / placeholder, posting is skipped.
