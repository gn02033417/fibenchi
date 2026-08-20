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
