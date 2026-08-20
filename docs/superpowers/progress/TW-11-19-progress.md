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
