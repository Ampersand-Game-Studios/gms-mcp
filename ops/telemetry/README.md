# Telemetry Ops

This folder contains the deploy-time assets for the privacy-safe telemetry pipeline:

- `cloudflare/`: ingestion worker, queue consumer, raw R2 storage, and daily rollups
- `archive/`: Mac mini archive puller and launchd job

The live path is:

1. Local spool on the user machine
2. `https://gms-mcp-telemetry.ampersandgamestudios.com/v1/events`
3. Cloudflare Queue
4. R2 raw storage + daily aggregate objects
5. Weekly archive bundle pulled by the Mac mini and uploaded to the Ampersand Shared Drive

Live telemetry must stay default-off and consent must remain user-scoped in `~/.gms-mcp/telemetry.json`.
