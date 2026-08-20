# TW-11～TW-19 Progress

## TW-11

Status: COMPLETE
Commit: 0e5af40

Verification:

- `backend\.venv\Scripts\python.exe -m pytest tests/services/shioaji/test_client.py tests/services/shioaji/test_kbars.py tests/services/test_shioaji_price_provider.py tests/services/test_historical_queue.py -q` — 20 passed.
- `backend\.venv\Scripts\ruff.exe check app/services/shioaji/client.py app/services/shioaji/kbars.py app/services/historical_queue.py tests/services/shioaji/test_client.py tests/services/shioaji/test_kbars.py tests/services/test_shioaji_price_provider.py tests/services/test_historical_queue.py` — passed.
- `git diff --check` — passed before commit.

Discoveries:

- `HistoricalDataQueue.fetch(asset, start, end)` uses inclusive calendar dates at both endpoints and splits requests into non-overlapping chunks of at most 30 days.
- The Shioaji sidecar boundary is `POST /api/v1/data/kbars`; its columnar response is normalized to Taiwan-time minute OHLCV values.
- The queue has no database dependency. Daily aggregation and persistence remain TW-12 scope.

## TW-12

Status: COMPLETE
Commit: 937548b

Verification:

- `backend\.venv\Scripts\python.exe -m pytest tests/services/shioaji/test_client.py tests/services/shioaji/test_kbars.py tests/services/test_shioaji_price_provider.py tests/services/test_historical_queue.py tests/services/test_daily_ohlcv.py tests/services/test_taiwan_price_sync.py tests/repositories/test_price_repo.py tests/services/test_price_sync.py tests/services/test_price_service.py tests/services/test_indicators_core.py -q` — 96 passed.
- `backend\.venv\Scripts\ruff.exe check` on TW-11/TW-12 source and focused tests — passed.
- `git diff --check` — passed before commit.

Discoveries:

- Taiwan sync reads persisted dates, computes only completed XTAI sessions, coalesces missing ranges, then routes them through the shared `HistoricalDataQueue`.
- Daily persistence is generated solely from normalized minute Kbars; an active XTAI session is excluded while the same session becomes eligible after close.
- Settled writes clear the indicator snapshot cache; the existing scheduled refresh then re-warms group caches.
- The temporary non-Taiwan compatibility branch remains isolated in `price_sync.py` for TW-18 cleanup and is not used by the Taiwan runtime path.

## TW-13

Status: COMPLETE
Commit: a25a720

Verification:

- `backend\.venv\Scripts\python.exe -m pytest tests/services/test_realtime_priority.py tests/services/test_group_service.py tests/repositories/test_group_repo.py tests/integration/test_groups.py -q` — 46 passed.
- `backend\.venv\Scripts\ruff.exe check` on TW-13 source and focused tests — passed.
- `corepack pnpm run lint` — passed.
- `corepack pnpm run build` — passed; Vite reported only the existing chunk-size warning.
- `git diff --check` — passed before commit.

Discoveries:

- `SHIOAJI_MAX_SUBSCRIPTIONS` defaults to 180 and is validated at configuration load time with a hard upper bound of 200.
- `compute_wanted_symbols(...)` is a pure, deterministic demand seam: active asset, realtime-priority groups, active group, recent symbols, then remaining tracked symbols; duplicate symbols always consume one slot.
- The existing group update endpoint provides the `realtime_priority` toggle round-trip; no subscription manager was introduced before TW-14.

## TW-14

Status: COMPLETE
Commit: 295ee50

Verification:

- `backend\.venv\Scripts\python.exe -m pytest tests/services/shioaji/test_stream.py tests/services/test_live_quote_store.py tests/services/test_subscription_manager.py -q` — 9 passed.
- Focused Shioaji and existing quote-service regression suite — 39 passed.
- `backend\.venv\Scripts\ruff.exe check` on TW-14 source and focused tests — passed.
- `git diff --check` — passed before commit.

Discoveries:

- The Shioaji sidecar Quote-only contract uses `POST /api/v1/stream/subscribe` / `unsubscribe` and one `GET /api/v1/stream/data/quote_stk` SSE connection.
- `SubscriptionManager` removes obsolete subscriptions before adding replacements, so it cannot exceed its validated 180-slot operational limit; a reconnect recomputes wanted subscriptions through its provider.
- `LiveQuoteStore` retains last-known values and explicitly emits `CACHED` for evicted symbols or `DISCONNECTED` after stream loss. Browser SSE wiring remains TW-15 scope.

## TW-15

Status: COMPLETE
Commit: 3d17a86

Verification:

- Focused lifecycle, quote-service, quote-router, store, manager, Shioaji client/stream and interval regression suite — 43 passed.
- `backend\.venv\Scripts\ruff.exe check` on TW-15 source and tests — passed.
- `git diff --check` — passed before commit.

Discoveries:

- The app lifespan owns one `LiveQuoteStore` and one `SubscriptionManager` task; startup subscriptions accept only AssetRefs with verified TSE/OTC exchange metadata.
- `/api/quotes/stream` keeps its path and `quotes` event format: it sends a current grouped-asset frame first, then only changed store values. Opening a browser SSE client does not call the price provider.
- Unknown tracked symbols are represented by explicit `DISCONNECTED` placeholders rather than fabricated prices; listener cleanup is covered on stream cancellation.

## TW-16

Status: COMPLETE
Commit: 9a5c32b

Verification:

- `backend\.venv\Scripts\python.exe -m pytest -q` — 913 passed; the new active-demand integration/focused suite — 20 passed.
- `backend\.venv\Scripts\python.exe -m ruff check app tests` — passed.
- `corepack pnpm run test` — 56 passed.
- `corepack pnpm run lint` — passed.
- `corepack pnpm run build` — passed; Vite reported only the existing chunk-size warning.
- `git diff --cached --check` — passed before commit.

Discoveries:

- The approved TW-13 demand seam was present as the pure priority allocator but had no browser registration path. TW-16 completes it through optional `active_asset` / `active_group` query parameters on the existing `/api/quotes/stream`; registration and removal follow the SSE connection lifetime, with immediate bounded diff reconciliation.
- `LIVE`, `CACHED`, and `DISCONNECTED` are rendered by the shared `QuoteFreshness` component at asset detail, group card/table, live-day, and Portfolio board tooltip price surfaces. `CACHED` and `DISCONNECTED` show the last update time when one exists and never use live styling.
- The existing per-symbol `QuoteStore` and reconnect path remain intact; active-view and intraday demand share the same debounced EventSource reopen.

## TW-17

Status: COMPLETE
Commit: 5c37087

Verification:

- `backend\\.venv\\Scripts\\python.exe -m pytest tests/services/test_intraday_aggregator.py tests/services/test_intraday.py tests/services/shioaji/test_stream.py tests/services/test_subscription_manager.py tests/services/test_quote_service.py tests/background_tasks/test_registry.py -q` — 58 passed.
- `backend\\.venv\\Scripts\\python.exe -m pytest -q` — 928 passed, 756 warnings.
- `backend\\.venv\\Scripts\\ruff.exe check app tests` — passed.
- `corepack pnpm run test` — 56 passed.
- `corepack pnpm run lint` — passed.
- `corepack pnpm run build` — passed; Vite reported only the existing chunk-size warning.
- `git diff --cached --check` — passed before commit.
- The ticket's `docker compose exec backend ...` command was not runnable because `docker` is not installed on this machine; the same focused pytest command passed directly in the repository backend venv.

Discoveries:

- Official Shioaji Quote events expose `volume` as the current tick volume and `total_volume` as cumulative volume since market open; `ShioajiQuoteUpdate` retains both before the public `Quote` mapping.
- `IntradayAggregator` owns Asia/Taipei/XTAI minute buckets, deduplicates event identities, emits a forming current bar and a completed prior bar on rollover, and persists only completed buckets through the existing `(asset_id, timestamp)` intraday key.
- Disconnects reset cumulative-volume attribution for the next event and mark the next real bar with `gap=True`; missing minutes are never synthesized. The 60-second Yahoo intraday task is disabled at scheduler resolution and is a no-op if invoked in Shioaji mode.

## TW-18

Status: COMPLETE
Commit: 1d747d2

Verification:

- `backend\.venv\Scripts\python.exe -m pytest tests/services/test_taiwan_runtime_has_no_yahoo.py -v` — 2 passed.
- Focused intraday, disabled holdings, and background registry suite — 38 passed.
- `backend\.venv\Scripts\python.exe -m pytest -q` — 921 passed, 752 warnings.
- `backend\.venv\Scripts\ruff.exe check app tests` — passed.
- `corepack pnpm run test` — 56 passed.
- `corepack pnpm run lint` — passed.
- `corepack pnpm run build` — passed; Vite reported only the existing chunk-size warning.
- `git diff --cached --check` — passed before commit.
- `docker compose run --rm backend pytest tests/services/test_taiwan_runtime_has_no_yahoo.py -v` — not runnable because `docker` is not installed on this machine; the same focused gate passed directly in the repository backend venv.

Discoveries:

- The Taiwan runtime no longer imports `app.services.yahoo`; the new AST and subprocess gate also proves the active app can import while blocking both `app.services.yahoo` and `yahooquery`.
- Yahoo-only earnings, ETF holdings, fundamentals, external-link settings, and remote symbol search UI are removed or hidden. Local Taiwan directory search remains the only frontend symbol-search path.
- The legacy Yahoo package and provider facade remain isolated for future reuse, while `yahooquery` is no longer a required runtime dependency. Legacy intraday persistence is isolated under `app.services.yahoo.legacy_intraday` and is no longer scheduled.
