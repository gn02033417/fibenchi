# TW-00～TW-10 Progress

Branch: `feature/tw-00-10-foundation`

## TW-00
Status: PARTIAL
Commit: `913c27c`
Verification:
- Backend baseline: 840 tests passed.
- Backend Ruff: passed.
- Frontend lint, build, and tests: passed.
- Production Docker image: not verified because Docker and alternate container runtimes are unavailable locally.
Discoveries:
- The local checkout was created from `dev` SHA `6a2a1062a2d006f4cd20bb85fd3e390eff92e528`.
- Upstream fork point is `c44c963b608f717a704f34446d940f0ddf406bae`.

## TW-01
Status: COMPLETE
Commit: `ee8c8d0`
Verification:
- Focused model/schema/migration test: 3 passed.
- Asset/group regression tests: 74 passed.
- Targeted Ruff: passed.
- Alembic reports `0021` as the single head.
Discoveries:
- Existing SymbolDirectory rows receive non-destructive `USD`/active defaults; Taiwan sync will provide verified TWD metadata later.

## TW-02
Status: COMPLETE
Commit: `a5a84d4`
Verification:
- Focused migration/service tests: 4 passed.
- Symbol sync, source, asset service, and asset integration regression: 71 passed.
- Targeted Ruff: passed.
Discoveries:
- Normalization is forward-only because raw symbols cannot reconstruct whether the source suffix was `.TW` or `.TWO`.

## TW-03
Status: COMPLETE
Commit: `6400d97`
Verification:
- Taiwan AssetRef tests: 5 passed.
- Existing market-calendar and repository regression: 47 passed.
- Targeted Ruff: passed.
Discoveries:
- Stored refs now resolve TSE/OTC from exchange metadata to equity/XTAI/TWD; unbound shape-only refs retain legacy behavior.

## TW-04
Status: PARTIAL
Commit: `7488227`
Verification:
- Shioaji client tests: 5 passed.
- Market-calendar, repository, and companion regression: 49 passed.
- Targeted Ruff: passed.
- Compose files parse as YAML; `docker compose config` not verified because Docker is unavailable locally.
Discoveries:
- Official sidecar boundary uses `/api/v1/health`, `/api/v1/info`, and `/api/v1/stream/status`; credentials are scoped to the sidecar service.

## TW-05
Status: COMPLETE
Commit: `143fc58`
Verification:
- Focused TWSE parser/provider tests: 4 passed.
- Existing symbol provider and sync regression: 33 passed.
- Symbol-source integration regression: 14 passed.
- Targeted Ruff: passed.
- Tests are fully offline; the ticket's Docker command was not run because Docker is unavailable locally.
Discoveries:
- Official TWSE OpenAPI sources are `t187ap03_L` for listed-company data and `t187ap47_L` for the fund/ETF master; raw codes remain strings.
- Category filtering uses official category fields and does not infer ETF type from code shape.

## TW-06
Status: COMPLETE
Commit: `d4e3446`
Verification:
- Focused TPEx parser/provider tests: 4 passed.
- TWSE/TPEx and existing provider, sync, and symbol-source regression: 51 passed.
- Targeted Ruff: passed.
- Tests are fully offline; the ticket's Docker command was not run because Docker is unavailable locally.
Discoveries:
- TPEx company reference data uses `mopsfin_t187ap03_O` with English field names; ETF reference data is exposed by the official ETF InfoHub table.
- ETF parsing uses explicit source/category metadata and does not classify by code shape; HTML parsing remains dependency-free.

## TW-07
Status: COMPLETE
Commit: `1a05ef3`
Verification:
- Contract adapter and client tests: 12 passed.
- Targeted Ruff: passed.
- Tests use Shioaji fixtures/stubs only; no real account or sidecar was used.
Discoveries:
- Official Shioaji 1.7 contract listing is `GET /api/v1/data/contracts` with `security_type=STK`; omitting pagination parameters requests the full set.
- Normalized records intentionally contain only raw `code` and `exchange`; empty or malformed upstream data raises `ShioajiContractSyncError` instead of becoming an empty delete set.

## TW-08
Status: COMPLETE
Commit: `12422f4`
Verification:
- Taiwan directory merge/sync tests: 4 passed.
- Existing symbol sync and scheduler registry regression: 17 passed.
- Taiwan model metadata regression: 3 passed.
- Symbol-source integration regression: 14 passed.
- Targeted Ruff: passed.
- Tests use injected providers/contracts and SQLite `db` fixture; Docker command was not run because Docker is unavailable locally.
Discoveries:
- Directory writes are deferred until both official sources and Shioaji contracts are usable; source failure returns `status=failed` without mutating last-known-good rows.
- The daily pre-market job is registered separately as `taiwan_symbol_directory_sync` at 07:00 Asia/Taipei, preserving the existing generic symbol job.

## TW-09
Status: COMPLETE
Commit: `5d7a3bb`
Verification:
- Focused search/asset service and integration tests: 52 passed.
- Existing asset repository, symbol sync, Taiwan directory, model metadata, scheduler, source, and AssetRef regression: 51 passed.
- Targeted Ruff: passed.
- Static runtime-path check confirms no Yahoo/Shioaji search or validation references remain in the TW-09 paths.
- Ticket Docker commands were not run because Docker is unavailable locally.
Discoveries:
- `source=local` and `source=all` remain compatibility inputs, but both execute the same local Taiwan directory search; `source=yahoo` is rejected by the API contract.
- Active TSE/OTC stock and ETF rows are the only searchable/creatable entries; directory name, exchange, official type, and TWD are authoritative at asset creation.
- The obsolete autouse Yahoo validation test fixture was removed because the Taiwan asset path no longer imports or calls `asset_service.yahoo_client`.

## TW-10
Status: COMPLETE
Commit: `0eab34b`
Verification:
- TDD red: the new provider test initially failed at collection because `app.services.price_providers.shioaji` did not exist.
- Focused Shioaji provider/client/quote regression: 56 passed before the final integration fixture adaptations.
- Final full backend suite: 873 passed, 751 warnings.
- Targeted Ruff check for changed backend files: passed.
- Frontend ESLint: passed via the existing `node_modules/.bin/eslint.cmd` binary.
- Frontend TypeScript/Vite production build: passed via the existing `node_modules/.bin/tsc.cmd` and `vite.cmd` binaries.
- Frontend Vitest: 7 files / 50 tests passed.
- No new Alembic migration in TW-10; TW-01/TW-02 migrations remain unchanged.
- Docker ticket commands were not run because Docker is unavailable locally.
Discoveries:
- The official snapshot endpoint is request-type data rather than a real-time quote subscription; mapped snapshots therefore use `data_status=CACHED`, while `LIVE` remains reserved for a future stream path.
- Snapshot mapping preserves raw Taiwan codes, derives previous close from the official change field when needed, maps official OHLC/bid/ask/volume fields, and attaches an explicit Asia/Taipei `updated_at`.
- Sidecar failures and missing snapshots return deterministic TWD `DISCONNECTED` placeholders without Yahoo fallback.
- Existing integration fixtures that create assets now seed Taiwan directory rows; local seeded bars cover the existing indicator warmup so tests do not invoke the not-yet-implemented TW-11 history seam.
- No historical queue/Kbars implementation, live SSE/subscription path, or other TW-11 scope was added.
