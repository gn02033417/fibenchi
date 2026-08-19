# Taiwan / Shioaji Ticket Tracker

This directory is the source of truth for Codex ticket-by-ticket implementation while GitHub Issues are disabled on this fork.

## Rules

- Execute in dependency order, not merely numeric order.
- Each ticket gets its own feature branch and PR to `dev`.
- Mark a ticket complete only after its PR is merged into `dev`.
- Do not edit future ticket scope from an implementation PR; propose plan/spec changes separately.
- Every Codex session reads `CLAUDE.md`, the architecture spec, the implementation plan, and the selected ticket.

## Tickets

- [ ] [TW-00](./TW-00.md) — Establish fork baseline and deterministic CI
- [ ] [TW-01](./TW-01.md) — Add Taiwan market schema metadata and realtime-priority fields
- [ ] [TW-02](./TW-02.md) — Migrate legacy Yahoo-style Taiwan symbols safely
- [ ] [TW-03](./TW-03.md) — Make Taiwan instrument identity metadata-aware
- [ ] [TW-04](./TW-04.md) — Add Shioaji sidecar runtime configuration and health client
- [ ] [TW-05](./TW-05.md) — Implement TWSE official reference-data adapter
- [ ] [TW-06](./TW-06.md) — Implement TPEx official reference-data adapter
- [ ] [TW-07](./TW-07.md) — Implement Shioaji Contracts adapter
- [ ] [TW-08](./TW-08.md) — Build Taiwan SymbolDirectory merge, sync and scheduling
- [ ] [TW-09](./TW-09.md) — Replace Yahoo search and asset validation with local Taiwan directory
- [ ] [TW-10](./TW-10.md) — Implement Shioaji Quote mapping and ShioajiPriceProvider
- [ ] [TW-11](./TW-11.md) — Implement HistoricalDataQueue and 30-day Kbars chunking
- [ ] [TW-12](./TW-12.md) — Aggregate Shioaji Kbars into settled daily OHLCV and gap-based sync
- [ ] [TW-13](./TW-13.md) — Add realtime-priority selection model and deterministic 180-slot wanted set
- [ ] [TW-14](./TW-14.md) — Implement SubscriptionManager and Shioaji live SSE ingestion
- [ ] [TW-15](./TW-15.md) — Replace poll-based backend quote SSE with event-driven live quote state
- [ ] [TW-16](./TW-16.md) — Add LIVE/CACHED/DISCONNECTED frontend UX and realtime demand signals
- [ ] [TW-17](./TW-17.md) — Build event-driven 1-minute intraday aggregation from live quotes
- [ ] [TW-18](./TW-18.md) — Disable Yahoo-only features and remove Yahoo from Taiwan runtime dependency path
- [ ] [TW-19](./TW-19.md) — End-to-end Taiwan release gate, Docker path and operator documentation

See `../plans/2026-08-19-fibenchi-shioaji-taiwan.md` for the dependency graph.