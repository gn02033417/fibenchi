// Assembles everything the dense board renders: the tile roster with per-tile
// σ/%/phase resolution, the section grouping, and the coverage numbers.
//
// σ resolution reuses the group table's exact cascade (computeLiveVnr →
// stored vnr unless isStoredVnrStale → explain the blank) so the board can
// never disagree with the table about the same asset.

import { useMemo } from "react"
import { type Asset, type Quote, type SparklinePoint } from "@/lib/api"
import {
  useDataHealth,
  useGroups,
  useIndicators,
  useMarketPhases,
  useSparklines,
  useTheses,
} from "@/lib/queries"
import { useQuotes } from "@/lib/quote-stream"
import {
  computeLiveVnr,
  getNumericValue,
  isStoredVnrStale,
} from "@/lib/indicator-registry"
import { marketState } from "@/lib/market-state"
import { VNR_BASELINE_SESSIONS, type PctWindow, PCT_WINDOWS } from "./color-scale"

export type Phase = "premarket" | "open" | "aftermarket" | "closed"

/** Why a tile has no σ reading.
 *
 * The variants are load-bearing *here* even though the tooltip only prints
 * `warmup`: `feed_behind` vs `gap` is what decides whether σ is withheld at
 * all, and the cascade below reads them to stay honest. Nothing downstream
 * discriminates them anymore — that is deliberate (all three non-warmup states
 * resolve to the same user action), not an oversight to be tidied away.
 */
export type NoReadingReason =
  | { kind: "feed_behind" }
  | { kind: "gap"; sessions: number; nextScanSeconds: number | null }
  | { kind: "warmup"; bars: number; needed: number }
  | { kind: "unknown" }

export interface Tile {
  /** The tile's identity — also its React key, route param and lookup key. */
  symbol: string
  /** The row behind the tile. Held whole rather than copied field by field, so
   * it satisfies AssetFormatHints directly (an index isn't
   * currency-denominated, a yield index is quoted in percent) and a new asset
   * field costs nothing here. */
  asset: Asset
  /** σ-Move via the live-first cascade; null → see reason. */
  sigma: number | null
  reason: NoReadingReason | null
  /** Today's % change (live quote first, stored bar fallback). */
  todayPct: number | null
  /** Last price — the magnitude behind the dimensionless σ (tooltip). */
  price: number | null
  /** Freshness metadata for the tooltip price. */
  data_status: Quote["data_status"]
  updated_at: Quote["updated_at"]
  /** % change over each board window (from the shared 1mo series). */
  windowPct: Record<PctWindow, number | null>
  /** The 1mo close series the windows were derived from (tooltip sparkline). */
  spark: SparklinePoint[]
  /** Sections this symbol belongs to under the active grouping (tooltip). */
  sections: string[]
  phase: Phase | null
  /** Venue calendar name + next scheduled phase change (tooltip). */
  calendar: string | null
  nextBell: string | null
  /** Whether the phase came from a live quote (vs the schedule fallback). */
  liveState: boolean
}

export interface BoardSection {
  key: string
  title: string
  /** Thesis colour edge (thesis grouping only). */
  accent: string | null
  tiles: Tile[]
}

export type GroupBy = "group" | "thesis"

/** Per-symbol % change series over the covering month, shared by the tiles'
 * %-mode, the Movers card, and the tooltips — one fetch, three windows.
 *
 * Fetched by roster, not by group: the board's symbols span every group and
 * (in thesis mode) some belong to none, so a per-group fetch both duplicated
 * shared symbols and missed thesis-only ones entirely. Returns the raw series
 * alongside the scalars — the tooltip sparkline draws from it, so reducing it
 * away here would mean fetching the same month twice.
 */
function useWindowReturns(symbols: string[]) {
  const { data: series } = useSparklines(symbols, "1mo")

  const quotes = useQuotes()
  const windows = useMemo(() => {
    const out: Record<string, Record<PctWindow, number | null>> = {}
    const today = new Date()
    for (const sym of symbols) {
      const points = series?.[sym]
      const per = {} as Record<PctWindow, number | null>
      for (const w of PCT_WINDOWS) {
        per[w.value] = null
        if (!points?.length) continue
        const cutoff = new Date(today)
        cutoff.setDate(cutoff.getDate() - w.days)
        const cutoffIso = cutoff.toISOString().slice(0, 10)
        // Baseline = last close at or before the window start; a series that
        // doesn't reach back that far has no honest answer for this window.
        let base: SparklinePoint | null = null
        for (const p of points) {
          if (p.date <= cutoffIso) base = p
          else break
        }
        if (!base || base.close === 0) continue
        const last = quotes[sym]?.price ?? points[points.length - 1].close
        per[w.value] = ((last - base.close) / base.close) * 100
      }
      out[sym] = per
    }
    return out
  }, [symbols, series, quotes])

  return { windows, series }
}

const EMPTY_WINDOWS: Record<PctWindow, number | null> = { "1wk": null, "2wk": null, "1mo": null }

export function useBoardData(groupBy: GroupBy) {
  const { data: groups, isLoading: groupsLoading } = useGroups()
  const { data: theses } = useTheses()
  const quotes = useQuotes()
  const { data: phases } = useMarketPhases()
  const { data: health } = useDataHealth()

  // The roster: every asset in any group — "the whole book". Assets known
  // only through a thesis still get tiles in thesis grouping.
  const roster = useMemo(() => {
    const bySymbol = new Map<string, Asset>()
    for (const g of groups ?? []) for (const a of g.assets) bySymbol.set(a.symbol, a)
    if (groupBy === "thesis")
      for (const t of theses ?? []) for (const a of t.assets) bySymbol.set(a.symbol, a)
    return bySymbol
  }, [groups, theses, groupBy])

  // What we *fetch* is the union over both groupings, deliberately wider than
  // what we render. The per-symbol queries key on their symbol array, so a
  // roster that grows when you switch to thesis mode would change the key and
  // miss cache on all ~84 snapshots for the sake of a handful of extra ones.
  // Keying on the union makes the Group ↔ Thesis toggle free.
  //
  // This is why useTheses() is not gated to thesis mode: the union needs it in
  // both. Gating it would save one ~4 KB request and reintroduce the refetch.
  const fetchSymbols = useMemo(() => {
    const all = new Set<string>()
    for (const g of groups ?? []) for (const a of g.assets) all.add(a.symbol)
    for (const t of theses ?? []) for (const a of t.assets) all.add(a.symbol)
    return [...all].sort()
  }, [groups, theses])

  const { data: snapshots } = useIndicators(fetchSymbols)
  const { windows: windowReturns, series } = useWindowReturns(fetchSymbols)

  // Which sections each symbol sits in, under the active grouping — the one
  // question the tooltip can answer that the grid can't, since a tile only
  // ever appears under one heading at a time.
  const sectionsBySymbol = useMemo(() => {
    const out: Record<string, string[]> = {}
    const add = (sym: string, title: string) => (out[sym] ??= []).push(title)
    if (groupBy === "group") {
      for (const g of groups ?? []) for (const a of g.assets) add(a.symbol, g.name)
    } else {
      for (const t of theses ?? []) for (const a of t.assets) add(a.symbol, t.name)
    }
    return out
  }, [groupBy, groups, theses])

  const symbolPhase = useMemo(() => {
    const out: Record<string, { calendar: string; phase: Phase; nextBell: string | null }> = {}
    for (const [cal, entry] of Object.entries(phases ?? {}))
      for (const sym of entry.symbols)
        out[sym] = { calendar: cal, phase: entry.phase, nextBell: entry.next_change_at }
    return out
  }, [phases])

  const tiles = useMemo(() => {
    const out = new Map<string, Tile>()
    for (const [symbol, asset] of roster) {
      const quote = quotes[symbol]
      const snap = snapshots?.[symbol]
      const values = snap?.values

      let sigma = computeLiveVnr(quote, values, snap?.close)
      let reason: NoReadingReason | null = null
      if (sigma == null) {
        const stale = isStoredVnrStale(quote, snap?.close)
        const stored = getNumericValue(values, "vnr")
        if (stored != null && !stale) {
          sigma = stored
        } else if (stale) {
          reason = { kind: "feed_behind" }
        } else {
          const gap = getNumericValue(values, "vnr_gap_sessions")
          const bars = snap?.bars ?? null
          if (gap != null) {
            reason = { kind: "gap", sessions: gap, nextScanSeconds: health?.next_scan_in_seconds ?? null }
          } else if (bars != null && bars < VNR_BASELINE_SESSIONS) {
            reason = { kind: "warmup", bars, needed: VNR_BASELINE_SESSIONS }
          } else {
            reason = { kind: "unknown" }
          }
        }
      }

      const scheduled = symbolPhase[symbol]
      const liveState = quote?.market_state != null
      const phase: Phase | null = liveState
        ? marketState(quote.market_state).phase
        : scheduled?.phase ?? null

      out.set(symbol, {
        symbol,
        asset,
        sigma,
        reason,
        todayPct: quote?.change_percent ?? snap?.change_pct ?? null,
        price: quote?.price ?? snap?.close ?? null,
        data_status: quote?.data_status ?? null,
        updated_at: quote?.updated_at ?? null,
        windowPct: windowReturns[symbol] ?? EMPTY_WINDOWS,
        spark: series?.[symbol] ?? [],
        sections: sectionsBySymbol[symbol] ?? [],
        phase,
        calendar: scheduled?.calendar ?? null,
        nextBell: scheduled?.nextBell ?? null,
        liveState,
      })
    }
    return out
  }, [roster, quotes, snapshots, windowReturns, series, sectionsBySymbol, symbolPhase, health])

  const sections = useMemo<BoardSection[]>(() => {
    const toTiles = (list: Asset[]) =>
      list.map((a) => tiles.get(a.symbol)).filter((t): t is Tile => !!t)
    if (groupBy === "group") {
      return (groups ?? [])
        .map((g) => ({ key: `g${g.id}`, title: g.name, accent: null, tiles: toTiles(g.assets) }))
        .filter((s) => s.tiles.length > 0)
    }
    const out: BoardSection[] = (theses ?? [])
      .map((t) => ({ key: `t${t.id}`, title: t.name, accent: t.color, tiles: toTiles(t.assets) }))
      .filter((s) => s.tiles.length > 0)
    const inThesis = new Set((theses ?? []).flatMap((t) => t.assets.map((a) => a.symbol)))
    const rest = [...tiles.values()].filter((t) => !inThesis.has(t.symbol))
    if (rest.length) out.push({ key: "no-thesis", title: "No thesis", accent: null, tiles: rest })
    return out
  }, [groupBy, groups, theses, tiles])

  const coverage = useMemo(() => {
    const all = [...tiles.values()]
    return {
      total: all.length,
      scored: all.filter((t) => t.sigma != null).length,
      open: all.filter((t) => t.phase === "open").length,
    }
  }, [tiles])

  return { sections, tiles, coverage, isLoading: groupsLoading }
}
