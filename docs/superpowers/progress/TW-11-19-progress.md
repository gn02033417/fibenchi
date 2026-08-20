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
