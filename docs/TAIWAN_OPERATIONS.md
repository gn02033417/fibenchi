# Taiwan operations runbook

This runbook covers the Shioaji-backed Taiwan deployment described by TW-19.

## Start and verify

1. Copy `.env.example` to `.env`.
2. Set `SJ_API_KEY` and `SJ_SEC_KEY` for the `shioaji` service. Keep them out of frontend variables and do not add them to the `app` service.
3. Choose `SJ_PRODUCTION=false` for simulation or `true` for the intended live Shioaji mode.
4. Start the production stack:

   ```bash
   docker compose -f docker-compose.prod.yaml up -d --build
   ```

5. Verify the application:

   ```bash
   curl http://localhost:18000/api/health
   docker compose -f docker-compose.prod.yaml ps
   docker compose -f docker-compose.prod.yaml logs --tail=100 app shioaji
   ```

The backend's typed sidecar checks are `/api/v1/health`, `/api/v1/info`, and `/api/v1/stream/status` on the internal Shioaji URL. They are not exposed as public browser endpoints.

## Freshness and failure states

- `LIVE` means the quote was received from the active Shioaji Quote stream.
- `CACHED` means the last known value remains available but the symbol is no longer in the bounded active subscription set.
- `DISCONNECTED` means the sidecar stream was lost. The last known timestamp remains visible, but the UI must not style the value as live.
- Reconnection rebuilds the wanted set because active browser demand and group priority may have changed while disconnected.

Historical charts and indicators continue from committed PostgreSQL daily rows while the live stream is unavailable. Historical Kbars are requested in chunks of at most 30 calendar days and are aggregated into completed Taiwan sessions. A forming current session may not be present until it settles.

## Reference and migration checks

The local symbol directory is active only where official TWSE/TPEx reference data intersects with Shioaji STK contract availability. Symbols are stored as raw Taiwan codes (`2330`, `0050`, `6488`) without `.TW` or `.TWO`.

For an existing installation, the forward migration normalizes proven numeric `.TW` and `.TWO` rows in place and preserves foreign keys and relationships. A collision such as both `2330` and `2330.TW` is a release blocker: the migration aborts before changing either table and must be resolved explicitly.

## Release checklist

Run the following in a container-capable environment before opening the `dev -> main` pull request:

```bash
docker compose -f docker-compose.prod.yaml config
docker compose -f docker-compose.yaml up -d --build
docker compose -f docker-compose.yaml exec backend pytest tests/integration/test_taiwan_e2e.py tests/integration/test_taiwan_migration_e2e.py -v
docker compose -f docker-compose.yaml exec backend pytest
docker compose -f docker-compose.yaml exec backend ruff check .
docker compose -f docker-compose.yaml exec frontend pnpm run lint
docker compose -f docker-compose.yaml exec frontend pnpm run build
docker build -t fibenchi:taiwan-release .
```

CI runs the same application checks with `httpx.MockTransport`; it never requires real Shioaji credentials or calls live TWSE, TPEx, or Shioaji services. The explicit sidecar health check is an operator/environment gate, not a CI test.

Implementation branches use the approved ticket names (`tw-11-*` through `tw-19-*`). Keep the architecture spec and implementation plan unchanged unless actual source behavior proves an irreconcilable conflict.
