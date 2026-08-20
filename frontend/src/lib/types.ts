// TypeScript types matching backend Pydantic schemas

import type { MarketState } from "./market-state"

export type AssetType = "stock" | "etf" | "index"

/** How an asset's price number reads. Distinct from `currency`, which only
 * answers *which* currency and so can't express a rate or a bare index level. */
export type UnitKind = "currency" | "percent" | "points"

/** Whether a stored field was derived by Fibenchi or chosen by the user.
 * Auto fields may be re-suggested when the guess improves; user fields are
 * never argued with. */
export type FieldSource = "auto" | "user"

/** Fibenchi's read on a ticker — advisory, never applied on its own.
 *
 * `differs` is every field the shape reads differently, whoever set it: these
 * are the resettable ones. `disagrees` is the auto-only subset — what may be
 * raised unprompted. A field you set stays in `differs` but leaves
 * `disagrees`, so it's still visible and reversible without nagging. */
export interface AssetSuggestion {
  type: AssetType
  unit_kind: UnitKind
  currency: string | null
  differs: string[]
  disagrees: string[]
}

export interface TagBrief {
  id: number
  name: string
  color: string
}

export interface Tag {
  id: number
  name: string
  color: string
  created_at: string
  assets: Asset[]
}

export interface TagCreate {
  name: string
  color?: string
}

export interface TagUpdate {
  name?: string
  color?: string
}

export interface Asset {
  id: number
  symbol: string
  name: string
  type: AssetType
  currency: string
  unit_kind: UnitKind
  type_source: FieldSource
  unit_source: FieldSource
  suggested?: AssetSuggestion | null
  created_at: string
  tags: TagBrief[]
}

/** What is attached to an asset — drives the remove dialog's orphan warning + hard-delete confirm. */
export interface AssetAttachments {
  symbol: string
  groups: string[]
  theses: string[]
  pseudo_etfs: string[]
  tags: string[]
  has_note: boolean
  annotation_count: number
}

export interface AssetCreate {
  symbol: string
  name?: string
  type?: AssetType
}

export interface AssetUpdate {
  name?: string
  type?: AssetType
  currency?: string
  unit_kind?: UnitKind
}

export interface SymbolSearchResult {
  symbol: string
  name: string
  exchange: string
  type: AssetType
}

export interface Group {
  id: number
  name: string
  description: string | null
  icon: string | null
  is_default: boolean
  realtime_priority: boolean
  position: number
  created_at: string
  assets: Asset[]
}

export interface GroupCreate {
  name: string
  description?: string
  icon?: string
}

export interface GroupUpdate {
  name?: string
  description?: string
  icon?: string
  realtime_priority?: boolean
}

export interface Price {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface Indicator {
  date: string
  close: number
  values: Record<string, number | null>
}

export interface AssetDetail {
  prices: Price[]
  indicators: Indicator[]
}

export interface Annotation {
  id: number
  date: string
  title: string
  body: string | null
  color: string
  created_at: string
}

export interface AnnotationCreate {
  date: string
  title: string
  body?: string
  color?: string
}

export interface Note {
  content: string
  updated_at: string
}

export type ThesisStatus = "watching" | "live" | "played_out"

export interface Thesis {
  id: number
  name: string
  color: string
  icon: string | null
  description: string | null
  status: ThesisStatus
  opened_at: string
  created_at: string
  // Full member rows (backend returns AssetResponse), so groupless members render too.
  assets: Asset[]
  aggregate_pct: number | null
}

export interface ThesisCreate {
  name: string
  color?: string
  icon?: string | null
  description?: string | null
  status?: ThesisStatus
  opened_at?: string
}

export interface ThesisUpdate {
  name?: string
  color?: string
  icon?: string | null
  description?: string | null
  status?: ThesisStatus
  opened_at?: string
}

export interface ThesisPerformancePoint {
  date: string
  pct: number
}

export interface ThesisPerformanceSeries {
  thesis_id: number
  points: ThesisPerformancePoint[]
}

export interface SyncResult {
  symbol: string
  synced: number
}

export interface Holding {
  symbol: string
  name: string
  percent: number
}

export interface SectorWeighting {
  sector: string
  percent: number
}

export interface EtfHoldings {
  top_holdings: Holding[]
  sector_weightings: SectorWeighting[]
  total_percent: number
}

export interface HoldingIndicator {
  symbol: string
  currency: string
  close: number | null
  change_pct: number | null
  values: Record<string, number | string | null>
}

export interface PortfolioIndex {
  dates: string[]
  values: number[]
  current: number
  change: number
  change_pct: number
}

export interface AssetPerformance {
  symbol: string
  name: string
  type: string
  change_pct: number
}

export interface PseudoETF {
  id: number
  name: string
  description: string | null
  base_date: string
  base_value: number
  created_at: string
  constituents: Asset[]
}

export interface PseudoETFCreate {
  name: string
  description?: string
  base_date: string
  base_value?: number
}

export interface PseudoETFUpdate {
  name?: string
  description?: string
  base_date?: string
}

export interface PerformanceBreakdownPoint {
  date: string
  value: number
  breakdown: Record<string, number>
}

export interface ConstituentIndicator {
  symbol: string
  name: string | null
  currency: string
  weight_pct: number | null
  close: number | null
  change_pct: number | null
  values: Record<string, number | string | null>
}

export interface SparklinePoint {
  date: string
  close: number
}

export interface IndicatorSummary {
  close: number | null
  change_pct: number | null
  /** Price bars behind the snapshot — distinguishes "building baseline" from other null-indicator causes. */
  bars: number | null
  values: Record<string, number | string | null>
}

/** Scheduled phase of one venue calendar (GET /api/market/phases).
 * Calendar-derived and quote-feed-independent; the SSE market_state wins when present. */
export interface CalendarPhase {
  phase: "premarket" | "open" | "aftermarket" | "closed"
  /** UTC instant of the next phase transition; null when unanswerable (e.g. 24/7 venues). */
  next_change_at: string | null
  /** Grouped symbols trading on this calendar — the symbol→venue mapping, served backend-side. */
  symbols: string[]
}

export interface SymbolSource {
  id: number
  name: string
  provider_type: string
  enabled: boolean
  config: Record<string, unknown>
  last_synced_at: string | null
  symbol_count: number
  created_at: string
}

export interface SymbolSourceCreate {
  name: string
  provider_type: string
  config?: Record<string, unknown>
}

export interface SymbolSourceUpdate {
  enabled?: boolean
  config?: Record<string, unknown>
  name?: string
}

export interface ProviderInfo {
  key: string
  label: string
  markets: { key: string; label: string }[]
}

export interface Quote {
  symbol: string
  price: number | null
  previous_close: number | null
  change: number | null
  change_percent: number | null
  volume: number | null
  avg_volume: number | null
  currency: string
  market_state: MarketState | null
  open: number | null
  high: number | null
  low: number | null
  bid: number | null
  bid_volume: number | null
  ask: number | null
  ask_volume: number | null
  data_status: "LIVE" | "CACHED" | "DISCONNECTED" | null
  updated_at: string | null
}

export interface IntradayPoint {
  time: number       // Unix timestamp
  price: number
  volume: number
  session: "pre" | "regular" | "post"
}

export interface EarningsInfo {
  earnings_date: string | null
  is_estimate: boolean
  last_reported_date: string | null
}

// --- System / data health ---

export interface HoleSymbol {
  symbol: string
  /** ISO dates of scheduled sessions with no stored bar */
  missing_sessions: string[]
}

/** Price-history self-heal status (GET /api/system/data-health). */
export interface DataHealth {
  hole_symbols: HoleSymbol[]
  total_missing_sessions: number
  /** Scheduled session bars in the scan window — completeness denominator */
  expected_session_bars: number
  /** Symbols the coverage scan can check — affected-count denominator */
  covered_symbols: number
  next_scan_in_seconds: number
  heals_per_scan: number
  scan_window_days: number
}

/** Collection-size numbers (GET /api/system/stats). */
export interface Stats {
  assets_total: number
  assets_tracked: number
  /** Ungrouped but kept because a thesis or pseudo-ETF references them */
  assets_thesis_or_etf_only: number
  /** Ungrouped and referenced by nothing — leftovers of removals */
  assets_orphaned: number
  stocks: number
  etfs: number
  indexes: number
  crypto: number
  futures: number
  fx: number
  price_bars: number
  earliest_bar: string | null
  latest_bar: string | null
  collected_days: number
  intraday_bars: number
  groups: number
  pseudo_etfs: number
  theses: number
  tags: number
  annotations: number
  symbol_directory_entries: number
}

/** An asset row referenced by nothing (GET /api/system/orphans). */
export interface OrphanAsset {
  id: number
  symbol: string
  name: string
  type: string
  /** stored daily bars that would be deleted with it — re-fetchable from Yahoo */
  price_bars: number
  latest_bar: string | null
  /** hand-written chart annotations that would be deleted with it — not re-fetchable */
  annotations: number
  /** whether a hand-written thesis note would be deleted with it — not re-fetchable */
  has_note: boolean
}
