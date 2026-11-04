# Release and operation contract

Work on `dev`, then promote `dev` → `pre-release` → `main`. A successful push-triggered CI run on these branches can publish to PyPI automatically. Manual CI dispatch does not publish. Do not push merely to test unless publication is authorized.

## Required release evidence

Install only the committed dependencies with `uv sync --frozen --all-extras`. Run:

```sh
uv run --frozen python3 cli/tests/python/run_all_tests.py
uv run --frozen python3 -m pytest cli/tests/python/test_final_verification.py
uv run --frozen python3 scripts/generate_quality_reports.py
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pyright
```

Final verification must execute every required child suite; missing, empty, all-skipped, or failed suites block it. Coverage requires 85% overall statements, 50% per module, and 75% measured branches. Test-source mentions are not executed MCP evidence.

CI runs the Python suite on Linux, Windows, and macOS. Licensed GameMaker certification requires both synthetic fixture families (`gm-2024` with runtime `2024.14.4.268`, `gm-2026-lts` with runtime `2026.0.0.23`) on all three host platforms. Each report must pass every semantic check, match the exact clean release commit, and use identical fixture source hashes across hosts. Missing or skipped certification blocks publication. Licensing is isolated in the branch-restricted `gamemaker-ci` environment and cleaned up after each job.

```sh
uv run --frozen python3 scripts/verify_release_certification.py build/release-certification \
  --expected linux-gm-2024 linux-gm-2026-lts windows-gm-2024 windows-gm-2026-lts macos-gm-2024 macos-gm-2026-lts \
  --expected-revision "$(git rev-parse HEAD)"
uv run --frozen python3 scripts/build_release.py --output-dir dist
```

The build uses locked build-backend tooling without an unlocked isolated environment, normalizes archive metadata to the source commit timestamp, builds twice, and requires byte-identical artifacts. Both builds and downloaded publication artifacts pass the package privacy allowlist. Existing output files are never deleted or overwritten. PyPI upload uses the pinned Trusted Publishing action only; the obsolete manual first-upload scripts were removed.

## Telemetry operation

The maintained Worker source, lockfile, tests, and deployment configuration are in `services/telemetry`. This replaces the missing local operations source recovered from the deployed `gms-mcp-telemetry-ingest` Worker. Runtime bindings continue to use the existing queue, R2 bucket, domain, and daily schedule; secrets are not included in source or distributions.

Before deployment, run `npm ci`, `npm run check`, `npm test`, `npm audit`, `npx wrangler whoami`, and `npx wrangler deploy --dry-run` in that directory. Deploy only to the configured account and read back `/health`, deployment version, bindings, and schedules. Preserve the archive credential unless rotation is authorized; for a rotation, update every archive consumer, verify authenticated export, and keep credentials outside the checkout.

The server validates closed metadata schemas, bounds both compressed and decompressed input, revalidates queued events, and writes deterministic per-event keys for delivery and client retries. Raw events are retained for 90 UTC days and identifier-free aggregates for 24 calendar months. Cleanup traverses all expired dates, including missed scheduled runs, even if aggregate generation fails; malformed or unrelated object keys are not deleted.

Ingestion requires JSON and a Cloudflare connection address. Before parsing, native rate-limit bindings allow approximately 60 requests per IP per minute and 300 requests per Cloudflare location per minute. Client-supplied forwarding headers and session/install IDs do not control these limits. The batch envelope rejects unknown keys, malformed send times, and duplicate IDs; event types must match their surface, and diagnostic categories and version formats are checked. IP addresses are used only by Cloudflare's rate limiter and never enter the telemetry queue or stored event data.

The single `IngestBudget` Durable Object applies atomic global limits of 300 accepted batches per UTC minute and 50,000 accepted events per UTC day. Its fixed counter record persists across Worker deployments and stores no request metadata. Each client network (IPv4 /24 or IPv6 /48) also has a 5,000-event daily share, checked first, in its own object named by a digest that changes every UTC day; that object holds only a counter and erases itself at the end of the day. Quota is reserved before queue submission, including failed submissions, to bound downstream growth conservatively. A protection outage returns 503 without enqueueing; exhausted quotas return 429 with `Retry-After`. Existing clients retain their bounded spool after upload failure. These limits bound ingestion, not total Cloudflare billing, and a public client cannot prove that an event describes genuine usage.

Retention is evaluated by UTC object-date prefixes: the cutoff day itself and all earlier dates expire. Raw retention keeps the last 90 UTC dates including the current day; aggregate cutoff calculation uses calendar months, not a 31-day approximation. The preview reports those exact cutoff dates before deletion.

Telemetry is optional, best-effort analytics, not a durable business-event store. The existing queue retains pending deliveries for 24 hours and retries failed consumption three times; prolonged failures can discard events. This bounded policy adds no recovery infrastructure. Recent daily aggregates are refreshed across the offline-client acceptance window so late events and retries are counted correctly. See [Cloudflare's retry-limit behavior](https://developers.cloudflare.com/queues/configuration/dead-letter-queues/).

Authenticated `GET /v1/admin/retention` previews cutoff dates/counts without reading event bodies. `POST` deletes only that expired population. Both require a retention-only temporary credential of the form `<expiry-unix-milliseconds>.<64-lowercase-hex-random-characters>`; archive export credentials grant no maintenance authority. Preview, explicitly authorize the exact deletion scope, execute, and read back a zero-expired preview. Allow credential propagation before retrying authorization, and remove the temporary credential after use. Never retrieve or publish production raw events for validation. Retention deletion is permanent; code rollback cannot restore deleted data.

For a bad deployment, use `npx wrangler deployments list --name gms-mcp-telemetry-ingest`, identify the last verified version, then use `npx wrangler rollback <version-id>` only with authorization. Verify the domain route and bindings afterward. Keep the current security/retention fixes unless the rollback is necessary to restore service.
