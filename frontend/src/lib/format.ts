import type { AssetType, UnitKind } from "@/lib/types"

/**
 * Pick a legible foreground (near-black or white) for content sitting on a solid
 * hex background — used so an icon stays readable on light swatches (amber/yellow/
 * lime) as well as dark ones. Falls back to white for malformed input.
 */
export function readableTextColor(hex: string): string {
  const h = hex.replace("#", "")
  if (h.length < 6) return "#ffffff"
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  // Perceived (sRGB-weighted) luminance, 0–1. Bright backgrounds → dark text.
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return lum > 0.6 ? "#1e293b" : "#ffffff"
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "\u20ac",
  GBP: "\u00a3",
  GBX: "\u00a3",
  ILS: "\u20aa",
  ILA: "\u20aa",
  ZAR: "R",
  JPY: "\u00a5",
  KRW: "\u20a9",
  CHF: "CHF\u00a0",
}

/**
 * What an asset needs to format its own price. `unit_kind` is the answer to
 * "how does this number read" and is the only thing consulted — `type` and
 * `symbol` are kept for callers and for the pre-unit_kind fallback below.
 *
 * This replaced a hardcoded four-ticker YIELD_INDICES set: percent-ness is a
 * property of the asset now, set by the backend and overridable by the user,
 * rather than a list in the frontend nothing outside it could reach.
 */
export interface AssetFormatHints {
  type: AssetType
  symbol: string
  currency: string
  // snake_case to match the API shape, so a whole `Asset` is a valid hint.
  unit_kind?: UnitKind
}

/** Assets fetched through endpoints that predate `unit_kind` don't carry one.
 * Falling back on `type` keeps them formatting as they always did rather than
 * printing a currency symbol on an index. */
function unitOf(asset: AssetFormatHints): UnitKind {
  return asset.unit_kind ?? (asset.type === "index" ? "points" : "currency")
}

const ZERO_DECIMAL_CURRENCIES = new Set(["KRW", "JPY", "IDR", "HUF", "VND", "CLP", "TWD"])

export function currencyDecimals(currency: string): number {
  return ZERO_DECIMAL_CURRENCIES.has(currency.toUpperCase()) ? 0 : 2
}

export function currencySymbol(currency: string): string {
  return CURRENCY_SYMBOLS[currency.toUpperCase()] ?? `${currency}\u00a0`
}

export function formatPrice(value: number, currency: string, decimals?: number, groupDigits = false): string {
  const d = decimals ?? currencyDecimals(currency)
  const fixed = value.toFixed(d)
  if (!groupDigits) return `${currencySymbol(currency)}${fixed}`
  const [int, frac] = fixed.split(".")
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  return `${currencySymbol(currency)}${frac !== undefined ? `${grouped}.${frac}` : grouped}`
}

export function formatAssetPrice(
  value: number,
  asset: AssetFormatHints,
  decimals?: number,
  groupDigits = false,
): string {
  const unit = unitOf(asset)
  if (unit === "currency") return formatPrice(value, asset.currency, decimals, groupDigits)
  const d = decimals ?? 2
  const fixed = value.toFixed(d)
  const [int, frac] = fixed.split(".")
  const grouped = groupDigits ? int.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : int
  const body = frac !== undefined ? `${grouped}.${frac}` : grouped
  return unit === "percent" ? `${body}%` : body
}

/** Significant figures kept by the compact abbreviation. Tuning knob, not a user setting. */
export const COMPACT_SIG_FIGS = 3

// Suffix bands, largest first. Compact abbreviation only kicks in at |value| >= 1,000.
const COMPACT_BANDS = [
  { threshold: 1e9, divisor: 1e9, suffix: "B" },
  { threshold: 1e6, divisor: 1e6, suffix: "M" },
  { threshold: 1e3, divisor: 1e3, suffix: "K" },
] as const

/**
 * Abbreviate `value` (|value| >= 1,000) to ~`sigFigs` significant figures with a
 * K/M/B suffix — adaptive decimals per band (2 for `1.xxK`, 1 for `xx.xK`, 0 for
 * `xxxK`). Trailing zeros are kept for uniform column width (`72.0K`, `1.40M`),
 * unlike the old fixed-1-decimal formatter that stripped `.0` and collapsed
 * distinct low-thousands prices (`1,007` and `1,042` both → `1.0K`).
 */
export function compactSigFig(value: number, sigFigs = COMPACT_SIG_FIGS): string {
  const abs = Math.abs(value)
  for (let i = 0; i < COMPACT_BANDS.length; i++) {
    const { threshold, divisor, suffix } = COMPACT_BANDS[i]
    if (abs < threshold) continue
    const scaled = value / divisor
    const intDigits = Math.floor(Math.abs(scaled)).toString().length
    const decimals = Math.max(0, sigFigs - intDigits)
    // Rounding can tip a value just under a band (e.g. 999,700 → "1000K"); when it
    // rolls to 4 integer digits, promote to the next band up (→ "1.00M").
    if (Math.abs(Number(scaled.toFixed(decimals))) >= 1000 && i > 0) {
      const up = COMPACT_BANDS[i - 1]
      const upScaled = value / up.divisor
      const upDecimals = Math.max(0, sigFigs - Math.floor(Math.abs(upScaled)).toString().length)
      return `${upScaled.toFixed(upDecimals)}${up.suffix}`
    }
    return `${scaled.toFixed(decimals)}${suffix}`
  }
  return value.toString()
}

export function formatCompactPrice(value: number, currency: string): string {
  // Below 1,000 the abbreviation buys no width, so keep full currency precision.
  if (Math.abs(value) < 1e3) return formatPrice(value, currency)
  return `${currencySymbol(currency)}${compactSigFig(value)}`
}

export function formatAssetCompactPrice(value: number, asset: AssetFormatHints): string {
  if (unitOf(asset) === "currency") return formatCompactPrice(value, asset.currency)
  return formatAssetPrice(value, asset, 2)
}

/**
 * Settings-aware asset price. When `compact`, returns the abbreviated form
 * (1.2K/3.4M) plus the full grouped price as `title` (for a hover tooltip);
 * otherwise the full price with optional thousands grouping. Encapsulates the
 * ternary previously duplicated across the asset card, table row, and detail header.
 */
export function formatAssetPriceWithSettings(
  value: number,
  asset: AssetFormatHints,
  opts: { compact?: boolean; group?: boolean },
): { text: string; title?: string } {
  const full = formatAssetPrice(value, asset, undefined, opts.group)
  if (!opts.compact) return { text: full }
  return { text: formatAssetCompactPrice(value, asset), title: full }
}

export function formatCompactNumber(value: number): string {
  // Same sig-fig rule as prices, for volume / chart axis / indicator cards.
  if (Math.abs(value) < 1e3) return value.toFixed(0)
  return compactSigFig(value)
}

export function changeColor(pct: number | null | undefined): string {
  if (pct == null) return "text-muted-foreground"
  return pct >= 0 ? "text-emerald-500" : "text-red-500"
}

export function formatChangePct(v: number | null): { text: string | null; className: string } {
  if (v === null) return { text: null, className: "" }
  const sign = v >= 0 ? "+" : ""
  return {
    text: `${sign}${v.toFixed(2)}%`,
    className: changeColor(v),
  }
}

/** Format an ISO date (`yyyy-mm-dd`) in the user's locale, e.g. "Feb 1, 2026". */
export function formatDateLong(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

/** Format an ISO date (`yyyy-mm-dd`) without the year, e.g. "Feb 1". */
export function formatDateShort(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })
}

/** Render the last quote update in the browser's local time, or nothing for an
 * unavailable/malformed timestamp. Freshness UI must never invent a time. */
export function formatQuoteUpdatedAt(value: string | null | undefined): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function buildYahooQuoteUrl(symbol: string): string {
  return `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}/`
}

/**
 * Build a Yahoo Finance advanced chart URL with pre-configured indicators.
 * Config includes: candlestick + volume, Bollinger Bands (20,2), RSI (14), MACD (12,26,9), 1Y daily.
 *
 * NOTE: Study key names contain invisible zero-width non-joiner characters (\u200c).
 * Yahoo Finance's chart config format requires these characters as delimiters in
 * study identifiers (e.g. "\u200cvol undr\u200c"). Removing them will break the
 * pre-configured chart layout when the URL is opened.
 */
export function buildYahooFinanceUrl(symbol: string): string {
  const config = {
    layout: {
      interval: "day",
      periodicity: 1,
      timeUnit: null,
      candleWidth: 7.77,
      flipped: false,
      volumeUnderlay: true,
      adj: true,
      crosshair: true,
      chartType: "candle",
      extended: true,
      marketSessions: { pre: true, post: true },
      aggregationType: "ohlc",
      chartScale: "linear",
      studies: {
        "\u200cvol undr\u200c": {
          type: "vol undr",
          inputs: { Series: "series", id: "\u200cvol undr\u200c", display: "\u200cvol undr\u200c" },
          outputs: { "Up Volume": "#0dbd6eee", "Down Volume": "#ff5547ee" },
          panel: "chart",
          parameters: { chartName: "chart", editMode: true, panelName: "chart" },
          disabled: false,
        },
        "\u200cBollinger Bands\u200c (20,2,ma,y)": {
          type: "Bollinger Bands",
          inputs: {
            Period: 20, Field: "field", "Standard Deviations": 2,
            "Moving Average Type": "ma", "Channel Fill": true,
            id: "\u200cBollinger Bands\u200c (20,2,ma,y)",
            display: "\u200cBollinger Bands\u200c (20,2,ma,y)",
          },
          outputs: { "Bollinger Bands Top": "auto", "Bollinger Bands Median": "auto", "Bollinger Bands Bottom": "auto" },
          panel: "chart",
          parameters: { chartName: "chart", editMode: true, panelName: "chart" },
          disabled: false,
        },
        "\u200crsi\u200c (14)": {
          type: "rsi",
          inputs: { Period: "14", Field: "field", id: "\u200crsi\u200c (14)", display: "\u200crsi\u200c (14)" },
          outputs: { RSI: "auto" },
          panel: "\u200crsi\u200c (14)",
          parameters: {
            studyOverZonesEnabled: true, studyOverBoughtValue: 80, studyOverBoughtColor: "auto",
            studyOverSoldValue: 20, studyOverSoldColor: "auto",
            chartName: "chart", editMode: true, panelName: "\u200crsi\u200c (14)",
          },
          disabled: false,
        },
        "\u200cmacd\u200c (12,26,9)": {
          type: "macd",
          inputs: {
            "Fast MA Period": 12, "Slow MA Period": 26, "Signal Period": 9,
            id: "\u200cmacd\u200c (12,26,9)", display: "\u200cmacd\u200c (12,26,9)",
          },
          outputs: { MACD: "auto", Signal: "#FF0000", "Increasing Bar": "#00DD00", "Decreasing Bar": "#FF0000" },
          panel: "\u200cmacd\u200c (12,26,9)",
          parameters: { chartName: "chart", editMode: true, panelName: "\u200cmacd\u200c (12,26,9)" },
          disabled: false,
        },
      },
      panels: {
        chart: {
          percent: 0.64, display: symbol, chartName: "chart", index: 0,
          yAxis: { name: "chart", position: null },
          yaxisLHS: [], yaxisRHS: ["chart", "\u200cvol undr\u200c"],
        },
        "\u200crsi\u200c (14)": {
          percent: 0.16, display: "\u200crsi\u200c (14)", chartName: "chart", index: 1,
          yAxis: { name: "\u200crsi\u200c (14)", position: null },
          yaxisLHS: [], yaxisRHS: ["\u200crsi\u200c (14)"],
        },
        "\u200cmacd\u200c (12,26,9)": {
          percent: 0.2, display: "\u200cmacd\u200c (12,26,9)", chartName: "chart", index: 2,
          yAxis: { name: "\u200cmacd\u200c (12,26,9)", position: null },
          yaxisLHS: [], yaxisRHS: ["\u200cmacd\u200c (12,26,9)"],
        },
      },
      setSpan: { multiplier: 1, base: "year", periodicity: { period: 1, timeUnit: "day" }, showEventsQuote: true, forceLoad: true },
      outliers: false,
      animation: true,
      headsUp: { static: true, dynamic: false, floating: false },
      lineWidth: 2,
      fullScreen: true,
      stripedBackground: true,
      color: "#0081f2",
      crosshairSticky: false,
      dontSaveRangeToLayout: true,
      symbols: [{
        symbol,
        symbolObject: { symbol, quoteType: "EQUITY", exchangeTimeZone: "America/New_York" },
        periodicity: 1, interval: "day", timeUnit: null,
        setSpan: { multiplier: 1, base: "year", periodicity: { period: 1, timeUnit: "day" }, showEventsQuote: true, forceLoad: true },
      }],
      renderers: [],
    },
    events: { divs: true, splits: true, tradingHorizon: "none", sigDevEvents: [] },
    drawings: null,
    preferences: {},
  }

  // btoa() only handles Latin1; encode UTF-8 bytes first for the \u200c characters in study keys
  const json = JSON.stringify(config)
  const bytes = new TextEncoder().encode(json)
  let binary = ""
  for (const b of bytes) binary += String.fromCharCode(b)
  const hash = btoa(binary)
  return `https://finance.yahoo.com/chart/${encodeURIComponent(symbol)}#${hash}`
}
