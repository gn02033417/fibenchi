// The tile tooltip: un-normalises the tile.
//
// σ-Move is what makes 84 assets comparable in one grid, and being
// dimensionless is exactly what it costs — the tile says *how unusual*, never
// *how much*. So this card hands back the magnitude, the recent path, and the
// context the grid had to throw away. Two rules follow:
//
//   1. Lead with whatever the tile isn't showing. In σ-mode the tile prints σ,
//      so the card leads with the % and the price; in %-mode it flips. Never
//      open with a number the cursor is already sitting on.
//   2. A line either carries something no other line can, or it doesn't exist.
//      That's what removes the phase from the meta row (the header states it),
//      the source note when the quote *is* live, and the chips when the symbol
//      only appears in one section.
//
// Nothing here fetches. Every value is already on the tile by the time the
// board renders, and hovering must stay free.

import type { SparklinePoint } from "@/lib/api"
import { QuoteFreshness } from "@/components/quote-freshness"
import { changeColor, formatAssetPrice, formatChangePct } from "@/lib/format"
import { rampColor, PCT_WINDOWS, type ColorMode } from "./color-scale"
import { BELL_VERB, PHASE_LABEL, countdown } from "./bell"
import { PhaseIcon } from "./tile"
import type { Tile } from "./use-board-data"

function fmtSigma(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}σ`
}

/** One month of closes, 130×42. Coloured by the month's own direction — not
 * today's, which the lead row already states and which would otherwise repaint
 * the whole path on a single red day. */
function Sparkline({ points, monthPct }: { points: SparklinePoint[]; monthPct: number | null }) {
  if (points.length < 2) return <div className="h-[42px] w-[130px]" />

  const closes = points.map((p) => p.close)
  const lo = Math.min(...closes)
  const hi = Math.max(...closes)
  const range = hi - lo || 1
  const stroke = monthPct != null && monthPct < 0 ? "var(--color-red-500)" : "var(--color-emerald-500)"

  // Drawn in a 0..1 unit box and stretched by the viewBox, so the geometry
  // stays independent of the rendered size; non-scaling-stroke keeps the line
  // 1.4px through that stretch.
  const d = closes
    .map((c, i) => `${i === 0 ? "M" : "L"}${(i / (closes.length - 1)).toFixed(4)},${((hi - c) / range).toFixed(4)}`)
    .join(" ")

  return (
    <svg
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      className="h-[42px] w-[130px] shrink-0 overflow-visible"
      aria-hidden
    >
      <path d={`${d} L1,1 L0,1 Z`} fill={stroke} fillOpacity={0.1} />
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={1.4}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

/** Warmup is the only no-reading state with a trajectory you can act on (wait)
 * and the only one whose progress is knowable, so it's the only one that gets a
 * shape of its own. The bar fills in --primary on --muted: system progress has
 * to sit visibly outside the value language, or it reads as a reading. */
function WarmupBar({ bars, needed }: { bars: number; needed: number }) {
  return (
    <div className="mt-1.5 flex items-center gap-2">
      <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${Math.min(100, (bars / needed) * 100)}%` }}
        />
      </div>
      <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-muted-foreground">
        {bars}/{needed} sessions
      </span>
    </div>
  )
}

export function TileTooltip({ tile, mode, span }: { tile: Tile; mode: ColorMode; span: number }) {
  // Rule 1: the pill carries whatever the tile is already encoding — same
  // value, same ramp colour, same ink — so the card and the tile you're
  // hovering visibly agree. The lead number is the other one.
  const encoded = mode === "sigma" ? tile.sigma : tile.todayPct
  const lead = mode === "sigma" ? tile.todayPct : tile.sigma
  const leadText =
    lead == null ? "—" : mode === "sigma" ? formatChangePct(lead).text : fmtSigma(lead)
  const stop = encoded == null ? null : rampColor(encoded, span)

  const warmup = tile.reason?.kind === "warmup" ? tile.reason : null
  const now = new Date()
  const bell = tile.nextBell ? new Date(tile.nextBell) : null
  const left = bell ? countdown(bell, now) : null

  const meta = [
    tile.calendar,
    bell && tile.phase
      ? `${BELL_VERB[tile.phase]} ${bell.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
      : null,
    left,
  ].filter(Boolean)

  return (
    <div className="w-[272px] overflow-hidden text-foreground">
      <div className="px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-[13px] font-semibold">{tile.symbol}</span>
          {tile.phase && (
            <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
              <PhaseIcon phase={tile.phase} live={tile.liveState} />
              {PHASE_LABEL[tile.phase]}
            </span>
          )}
        </div>
        {tile.asset.name && <div className="mt-0.5 text-[11.5px] leading-snug text-muted-foreground">{tile.asset.name}</div>}
      </div>

      <div className="border-t border-border px-3 py-2">
        <div className="flex items-baseline gap-2">
          <span className={`text-[17px] font-semibold tabular-nums ${changeColor(lead)}`}>{leadText}</span>
          {/* formatAssetPrice, not formatPrice: an index isn't
              currency-denominated, and a yield index (^TYX, ^TNX, …) is quoted
              in percent — a "$" in front of a 30-year Treasury yield is a
              category error, not a cosmetic one. */}
          {tile.price != null && (
            <span className="text-[13px] font-medium tabular-nums text-muted-foreground">
              {formatAssetPrice(tile.price, tile.asset)}
            </span>
          )}
          <QuoteFreshness quote={tile} />
          {/* Everything that isn't warmup — feed_behind, gap, unknown — lands
              here as a plain em dash. All three resolve to the same user
              action, so they get the same shape and no prose. */}
          {stop ? (
            <span
              className="ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular-nums"
              style={{ backgroundColor: stop.color, color: stop.ink }}
            >
              {mode === "sigma" ? fmtSigma(encoded!) : formatChangePct(encoded!).text}
            </span>
          ) : (
            <span className="ml-auto shrink-0 text-[13px] text-muted-foreground">—</span>
          )}
        </div>
        {warmup && <WarmupBar bars={warmup.bars} needed={warmup.needed} />}
      </div>

      <div className="flex items-center gap-3 border-t border-border px-3 py-2">
        {/* The curve is the same month the table's bottom row measures, but
            nothing about it says so — it's the one element here with no units,
            and it reads as "recent" rather than as a span. The label is the
            cheapest way to make it a statement instead of a mood. */}
        <div className="shrink-0">
          <Sparkline points={tile.spark} monthPct={tile.windowPct["1mo"]} />
          <div className="mt-0.5 text-center text-[10px] text-muted-foreground">1mo</div>
        </div>
        <table className="flex-1 text-[11px]">
          <tbody>
            {PCT_WINDOWS.map((w) => {
              const v = tile.windowPct[w.value]
              return (
                <tr key={w.value}>
                  <td className="pr-2 text-muted-foreground">{w.label}</td>
                  <td className={`text-right tabular-nums ${changeColor(v)}`}>
                    {v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="space-y-1 border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
        {/* Only when the symbol is in more than one — this is the one question
            the grid can't answer, since a tile appears under a single heading.
            At one section, that heading already said it. */}
        {tile.sections.length > 1 && (
          <div className="flex flex-wrap gap-1">
            {tile.sections.map((s) => (
              <span key={s} className="rounded bg-muted px-1.5 py-0.5 text-[10.5px] text-foreground">
                {s}
              </span>
            ))}
          </div>
        )}
        {meta.length > 0 && <div>{meta.join(" · ")}</div>}
        {tile.liveState === false && (
          <div className="text-amber-500">phase from the calendar — no live quote</div>
        )}
      </div>
    </div>
  )
}
