# fibenchi

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A self-hosted Taiwan investment-research dashboard for tracking stocks, ETFs, and custom baskets. Fibenchi stores daily OHLCV history, computes technical indicators, streams Shioaji quotes through a server-side SSE boundary, and keeps notes, annotations, tags, theses, and pseudo-ETFs in PostgreSQL.

## Taiwan runtime

The supported market path is Taiwan TSE/OTC only:

`TWSE/TPEx reference data + Shioaji STK contracts -> local SymbolDirectory -> FastAPI -> React`

The browser never connects to Shioaji and never receives `SJ_API_KEY` or `SJ_SEC_KEY`. The backend talks to the internal Shioaji sidecar; CI uses HTTP stubs and does not require a brokerage account or live TWSE/TPEx services.

## Features

- **Groups** — Organize assets into named groups with table, card, live-quote, and indicator-scanner views
- **Taiwan symbol directory** — Search by raw code or Chinese name; active TSE/OTC stock and ETF rows are backed by official reference data and Shioaji contract availability
- **Price charts** — Candlestick or line charts with SMA, Bollinger Bands, RSI, MACD, ATR, and ADX via [lightweight-charts](https://github.com/tradingview/lightweight-charts)
- **Real-time quotes** — Server-sent events expose explicit `LIVE`, `CACHED`, and `DISCONNECTED` freshness states; the bounded Shioaji pool defaults to 180 subscriptions
- **Historical prices** — Shioaji Kbars are fetched in bounded ranges and aggregated into settled Taiwan daily OHLCV rows in PostgreSQL
- **Pseudo-ETFs** — Custom baskets with equal-weight allocation, quarterly rebalancing, indexed performance tracking, and synced crosshairs
- **Portfolio overview** — Composite equal-weight index of tracked assets with top/bottom performer rankings
- **Theses, notes, annotations, and tags** — Research context attached to assets and groups
- **Mobile companion app** — A separate React Native / Expo app can read the companion API as a configuration plane
- **Dark mode** — Light, dark, and system themes

## Tech stack

| Layer    | Technology |
|----------|------------|
| Backend  | Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, APScheduler |
| Frontend | React 19, TypeScript, TanStack React Query, Tailwind CSS, shadcn/ui |
| Market data | TWSE/TPEx reference providers and Shioaji Server 1.7.0 sidecar |
| Charts   | lightweight-charts v5 |
| Infra    | Docker Compose, GitHub Actions CI/CD, GHCR |

## Quick start

```bash
git clone https://github.com/jvanmelckebeke/fibenchi.git
cd fibenchi
cp .env.example .env
# Set SJ_API_KEY and SJ_SEC_KEY in .env for live Shioaji data.
docker compose up -d --build
```

The development stack is available at:

- Frontend: http://localhost:5173
- Backend API: http://localhost:18000/api
- API docs: http://localhost:18000/docs
- Backend health: http://localhost:18000/api/health

For a credential-free local smoke run, leave the Shioaji credentials empty and use the offline test suite. Live quotes and real contract/Kbars requests require valid sidecar credentials.

## Production

The production image builds the React SPA and serves it from the Python application image:

```bash
docker compose -f docker-compose.prod.yaml up -d --build
```

Production credential flow is intentionally one-way:

- `SJ_API_KEY` and `SJ_SEC_KEY` are environment variables of the `shioaji` service only.
- The `app` service receives only `SHIOAJI_BASE_URL`, timeout, subscription-limit, database, and scheduler settings.
- No Shioaji credential is a Vite variable, frontend source value, Docker build argument, or public API response.

Check the public backend with `GET /api/health`. From inside the Compose network, the sidecar exposes the typed health checks used by the backend at `/api/v1/health`, `/api/v1/info`, and `/api/v1/stream/status`.

The API has no built-in authentication. Put the service behind a reverse proxy, VPN, or equivalent access control before exposing it to a network. Set a strong `POSTGRES_PASSWORD` in production.

## Configuration

All variables are listed in `.env.example`.

| Variable | Default | Used by | Description |
|----------|---------|---------|-------------|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `fibenchi` / required in prod / `fibenchi` | `db`, `app` | PostgreSQL connection settings |
| `DATABASE_URL` | Compose-generated URL | `backend` | Async PostgreSQL connection string |
| `REFRESH_CRON` | `0 23 * * *` | `app` | Daily settled-price refresh schedule |
| `SJ_API_KEY` | empty | `shioaji` only | Shioaji account key; never pass to `app` or frontend |
| `SJ_SEC_KEY` | empty | `shioaji` only | Shioaji secret key; never pass to `app` or frontend |
| `SJ_PRODUCTION` | `false` | `shioaji` | Shioaji simulation/live mode |
| `SJ_HTTP_ADDR` | `0.0.0.0:8080` | `shioaji` | Internal sidecar bind address |
| `SHIOAJI_BASE_URL` | `http://shioaji:8080` | `app` | Internal sidecar URL |
| `SHIOAJI_TIMEOUT_SECONDS` | `5` | `app` | Sidecar HTTP/SSE timeout |
| `SHIOAJI_MAX_SUBSCRIPTIONS` | `180` | `app` | Operational Quote cap; configuration hard limit is 200 |

## Data limitations and explicit non-goals

- This release covers Taiwan TSE/OTC stocks and ETFs only. Raw symbols are stored without `.TW` or `.TWO` suffixes.
- Historical daily rows are derived from Shioaji minute Kbars and only completed venue sessions are persisted. A current forming session may be absent until it settles.
- A sidecar disconnect keeps the last known timestamp but marks the quote `DISCONNECTED`; it must not be presented as `LIVE`. Symbols outside the bounded subscription set are `CACHED` when their live slot is evicted.
- No order placement, trading, broker position sync, account management, or portfolio execution is included.
- Fundamentals, Earnings, ETF Holdings, Yahoo-specific links, overseas assets, and Yahoo remote search are intentionally disabled or hidden in the Taiwan build.
- CI and the release gate do not call real Shioaji, TWSE, or TPEx services. Live credential/sidecar verification remains an operator check in a container-capable environment.

## Development and release workflow

Each approved ticket is implemented on its named `tw-NN-*` branch. Keep the architecture spec, implementation plan, and ticket scope as the source of truth; reassess only when the actual codebase has an irreconcilable conflict with them.

Before opening a `dev` pull request, run the focused Taiwan gate and the full backend/frontend checks. After the `TW-19` release gate is green and `dev` has been validated, open the `dev -> main` pull request. Do not treat a successful build alone as proof of live sidecar health.

## Tests and release checks

```bash
# Backend focused release gate
docker compose exec backend pytest tests/integration/test_taiwan_e2e.py tests/integration/test_taiwan_migration_e2e.py -v

# Backend full checks
docker compose exec backend pytest
docker compose exec backend ruff check .

# Frontend checks
docker compose exec frontend pnpm run lint
docker compose exec frontend pnpm run build
docker compose exec frontend pnpm run test

# Production image and Compose syntax
docker build -t fibenchi:taiwan-release .
docker compose -f docker-compose.prod.yaml config
```

The E2E tests use `httpx.MockTransport` for contracts, Kbars, Quote subscriptions, and SSE. They verify the complete local chain without real market services or credentials.

## Project structure

```
fibenchi/
├── backend/
│   ├── app/
│   │   ├── models/            # SQLAlchemy models and relationships
│   │   ├── schemas/           # Pydantic request/response contracts
│   │   ├── routers/           # FastAPI route handlers
│   │   ├── services/
│   │   │   ├── shioaji/       # Typed sidecar client, contracts, Kbars, Quote SSE
│   │   │   ├── symbol_providers/ # TWSE/TPEx reference adapters
│   │   │   ├── compute/       # Indicator and group calculations
│   │   │   ├── historical_queue.py
│   │   │   ├── subscription_manager.py
│   │   │   ├── price_sync.py
│   │   │   └── price_service.py
│   │   └── main.py            # App entrypoint, scheduler, realtime lifecycle
│   └── tests/
│       └── integration/       # API and Taiwan release gates
├── frontend/
│   └── src/                   # React pages, components, API, SSE, indicators
├── docker-compose.yaml        # Development environment
├── docker-compose.prod.yaml   # Production environment
├── Dockerfile                 # Multi-stage production image
└── .github/workflows/         # Offline tests and image build/publish
```
