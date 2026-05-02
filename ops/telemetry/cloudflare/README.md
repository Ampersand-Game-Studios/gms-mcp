# Cloudflare Telemetry Backend

This worker is the first-party telemetry backend for `gms-mcp`.

## Resources

- Worker: `gms-mcp-telemetry-ingest`
- Queue: `gms-mcp-telemetry-events`
- R2 bucket: `gms-mcp-telemetry-prod`
- Route: `gms-mcp-telemetry.ampersandgamestudios.com/v1/events`

## Responsibilities

- `fetch`: accept event batches, reject oversized or malformed payloads, drop unknown fields, and queue sanitized events only.
- `fetch`: enforce a per-client in-worker ingest rate limit before queue writes.
- `fetch`: expose authenticated archive export endpoints for the Mac mini at `/v1/archive/manifest` and `/v1/archive/object`.
- `queue`: persist immutable raw NDJSON batches to R2 under `raw/YYYY/MM/DD/...`.
- `scheduled`: roll up the previous day's raw events into `aggregates/YYYY/MM/DD/summary.json` and prune retention cutoffs.

## Deploy

```bash
cd ops/telemetry/cloudflare
npm install
npx wrangler deploy
```

## Required Cloudflare bindings

- Queue producer binding: `TELEMETRY_QUEUE`
- Queue consumer queue: `gms-mcp-telemetry-events`
- R2 binding: `TELEMETRY_BUCKET`
- Vars:
  - `RAW_RETENTION_DAYS=90`
  - `AGGREGATE_RETENTION_MONTHS=24`
- Secret:
  - `TELEMETRY_ARCHIVE_TOKEN`

## Recommended Cloudflare controls

- Keep a Cloudflare rate limit rule on `POST /v1/events` as the outer enforcement layer
- Add a WAF rule limited to the telemetry hostname
- Disable or minimize request logging retention on the ingestion route
- Keep the worker route separate from the marketing website zone rules
