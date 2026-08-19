# Fibenchi Taiwan / Shioaji Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Fibenchi into a pure Taiwan-market research/monitoring system for TSE stocks, OTC stocks, and Taiwan ETFs, with Shioaji as the only market-data source.

**Architecture:** Keep Fibenchi as the browser/API boundary, place the official Shioaji HTTP/SSE server in a sidecar, persist normalized Taiwan reference/history data in PostgreSQL, and preserve the existing `PriceProvider`/Groups/Tags/Thesis/indicator seams. Realtime data is event-driven with a deterministic 180-slot subscription allocator; historical data is gap-filled from Shioaji Kbars in <=30-day chunks.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL, APScheduler, React 19, TypeScript, TanStack Query, SSE, Docker Compose, Shioaji HTTP/SSE sidecar, TWSE/TPEx official reference data.

**Spec:** `docs/superpowers/specs/2026-08-19-fibenchi-shioaji-taiwan-design.md`

## Global Constraints

- Raw Taiwan symbols remain strings (`2330`, `6488`, `0050`); preserve leading zeroes.
- TSE/OTC metadata comes from verified data, never symbol heuristics.
- Stock-vs-ETF comes from TWSE/TPEx official reference data.
- Shioaji is the only Taiwan runtime quote/history/intraday provider.
- Browser never connects to Shioaji and never receives credentials.
- Realtime operational cap: `SHIOAJI_MAX_SUBSCRIPTIONS=180`.
- No Snapshot/Kbars/Ticks polling as a fake realtime feed.
- Historical calls are rate-limited/de-duplicated and chunked to <=30 days.
- Settled daily OHLCV lives in PostgreSQL; indicators consume local settled data.
- CI uses fixtures/stubs only; no real brokerage account or live-market dependency.
- First release excludes trading, positions sync, overseas markets, futures/options/warrants, fundamentals provider, earnings, and ETF holdings.

---

## Branch Policy

- `main`: stable/release only.
- `dev`: Taiwan integration branch.
- Every ticket: feature branch from current `dev` -> PR to `dev`.
- Do not start a dependent ticket until prerequisite PRs are merged.
- Final release: `dev` -> `main` only after TW-19 passes.

## Execution Graph

```text
TW-00
 ├─> TW-01 -> TW-02 -> TW-03
 ├─> TW-04 -> TW-07
 ├─> TW-05
 └─> TW-06

TW-01 + TW-05 + TW-06 + TW-07 -> TW-08 -> TW-09
TW-03 + TW-04 -> TW-10
TW-03 + TW-04 -> TW-11
TW-03 + TW-10 + TW-11 -> TW-12
TW-01 + TW-09 -> TW-13
TW-07 + TW-10 + TW-13 -> TW-14 -> TW-15 -> TW-16
TW-03 + TW-14 + TW-15 -> TW-17
TW-09 + TW-10 + TW-12 + TW-15 + TW-17 -> TW-18
TW-00..TW-18 -> TW-19
```

## Ticket Index

- [TW-00](../tickets/TW-00.md) — Establish fork baseline and deterministic CI
- [TW-01](../tickets/TW-01.md) — Add Taiwan market schema metadata and realtime-priority fields
- [TW-02](../tickets/TW-02.md) — Migrate legacy Yahoo-style Taiwan symbols safely
- [TW-03](../tickets/TW-03.md) — Make Taiwan instrument identity metadata-aware
- [TW-04](../tickets/TW-04.md) — Add Shioaji sidecar runtime configuration and health client
- [TW-05](../tickets/TW-05.md) — Implement TWSE official reference-data adapter
- [TW-06](../tickets/TW-06.md) — Implement TPEx official reference-data adapter
- [TW-07](../tickets/TW-07.md) — Implement Shioaji Contracts adapter
- [TW-08](../tickets/TW-08.md) — Build Taiwan SymbolDirectory merge, sync and scheduling
- [TW-09](../tickets/TW-09.md) — Replace Yahoo search and asset validation with local Taiwan directory
- [TW-10](../tickets/TW-10.md) — Implement Shioaji Quote mapping and ShioajiPriceProvider
- [TW-11](../tickets/TW-11.md) — Implement HistoricalDataQueue and 30-day Kbars chunking
- [TW-12](../tickets/TW-12.md) — Aggregate Shioaji Kbars into settled daily OHLCV and gap-based sync
- [TW-13](../tickets/TW-13.md) — Add realtime-priority selection model and deterministic 180-slot wanted set
- [TW-14](../tickets/TW-14.md) — Implement SubscriptionManager and Shioaji live SSE ingestion
- [TW-15](../tickets/TW-15.md) — Replace poll-based backend quote SSE with event-driven live quote state
- [TW-16](../tickets/TW-16.md) — Add LIVE/CACHED/DISCONNECTED frontend UX and realtime demand signals
- [TW-17](../tickets/TW-17.md) — Build event-driven 1-minute intraday aggregation from live quotes
- [TW-18](../tickets/TW-18.md) — Disable Yahoo-only features and remove Yahoo from Taiwan runtime dependency path
- [TW-19](../tickets/TW-19.md) — End-to-end Taiwan release gate, Docker path and operator documentation

## Codex Workflow Per Ticket

1. Read `CLAUDE.md`.
2. Read the architecture spec.
3. Read this plan and the current ticket; inspect only prerequisite changes needed for context.
4. Create the ticket feature branch from current `dev`.
5. Write a focused failing test before production changes.
6. Implement only the ticket contract.
7. Run focused tests, then neighboring regression gates.
8. Commit with the ticket ID and open a PR to `dev`.
9. Merge only after acceptance criteria are satisfied.
10. Move to the next dependency-ready ticket.

## Review Boundary

Schema/identity, official reference adapters, Shioaji runtime, historical data, realtime subscriptions, browser SSE, frontend freshness UX, intraday aggregation, Yahoo retirement, and release verification are intentionally separate. A ticket must not absorb later work merely because adjacent files are touched.