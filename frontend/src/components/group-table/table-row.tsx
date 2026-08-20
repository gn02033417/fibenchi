import { memo, useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { ChevronRight, ChevronDown } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { ContextMenu, ContextMenuTrigger } from "@/components/ui/context-menu"
import { EditAssetDialog } from "@/components/assets/edit-asset-dialog"
import { TagBadge } from "@/components/tags/tag-badge"
import { MarketStatusDot } from "@/components/market-status-dot"
import { ExpandedAssetChart } from "@/components/chart/expanded-asset-chart"
import type { Asset, Quote, IndicatorSummary } from "@/lib/api"
import { formatAssetPriceWithSettings, formatCompactNumber, readableTextColor } from "@/lib/format"
import { ChangePct } from "@/components/change-pct"
import { QuoteFreshness } from "@/components/quote-freshness"
import {
  getNumericValue,
  extractMacdValues,
  formatDeltaAnnotation,
  getDescriptorByField,
  formatIndicatorField,
  computeLiveVnr,
  isStoredVnrStale,
} from "@/lib/indicator-registry"
import { marketState as marketStateInfo } from "@/lib/market-state"
import { usePriceFlash } from "@/lib/use-price-flash"
import { useSettings } from "@/lib/settings"
import { resolveIcon } from "@/lib/icon-utils"
import { isColumnVisible } from "./shared"

export interface RowMenuContext {
  asset: Asset
  openEdit: () => void
  openNewThesis: () => void
}

/** Caller-supplied row context menu — keeps `TableRow` ignorant of groups/theses. */
export type RowMenuRenderer = (ctx: RowMenuContext) => ReactNode

function LazyExpandedChart({ symbol, currency }: { symbol: string; currency: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: "200px" },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={ref}>
      {visible ? (
        <ExpandedAssetChart symbol={symbol} currency={currency} compact />
      ) : (
        <Skeleton className="h-[200px] lg:h-[300px] w-full rounded-md" />
      )}
    </div>
  )
}

export const TableRow = memo(function TableRow({
  asset,
  quote,
  indicator,
  expanded,
  onToggle,
  onHover,
  compactMode,
  columnSettings,
  visibleIndicatorFields,
  totalColSpan,
  renderContextMenu,
  onNewThesis,
  accent,
  accentTitle,
  accentIcon,
}: {
  asset: Asset
  quote?: Quote
  indicator?: IndicatorSummary
  expanded: boolean
  onToggle: (symbol: string) => void
  onHover: (symbol: string) => void
  compactMode: boolean
  columnSettings: Record<string, boolean>
  visibleIndicatorFields: string[]
  totalColSpan: number
  renderContextMenu?: RowMenuRenderer
  /** Open the (table-owned, single) "new thesis for this asset" dialog. */
  onNewThesis?: (asset: Asset) => void
  /** Left-border accent colour (thesis colour) for the "inline" thesis grouping. */
  accent?: string
  /** Tooltip for the accent bar — the thesis name(s) this row belongs to. */
  accentTitle?: string
  /** Lucide icon name (the thesis icon) revealed when the accent bar expands on hover. */
  accentIcon?: string
}) {
  // Use live SSE quote when available, fall back to DB-cached indicator values
  const livePrice = quote?.price ?? null
  const livePct = quote?.change_percent ?? null
  const displayPrice = livePrice ?? indicator?.close ?? null
  const displayPct = livePct ?? indicator?.change_pct ?? null

  // Stale = we have DB data but no live quote yet
  const hasLiveQuote = livePrice != null
  const hasDbFallback = !hasLiveQuote && displayPrice != null
  // Suppress stale indicator when market is closed — DB prices are already current.
  // When no quote yet, market_state is unknown so we assume market hours (show stale).
  // The POSTPOST-counts-as-closed knowledge lives in the shared trait table.
  const marketState = quote?.market_state
  const isMarketClosed = marketState != null && marketStateInfo(marketState).phase === "closed"
  const showStale = hasDbFallback && !isMarketClosed

  const { settings } = useSettings()
  const [priceRef, pctRef] = usePriceFlash(displayPrice)
  const py = compactMode ? "py-1.5" : "py-2.5"
  const staleClass = showStale ? "stale-price" : ""
  const priceFmt = displayPrice != null && isColumnVisible(columnSettings, "price")
    ? formatAssetPriceWithSettings(displayPrice, asset, {
        compact: settings.compact_numbers,
        group: settings.thousands_separator,
      })
    : null

  const handleToggle = useCallback(() => onToggle(asset.symbol), [onToggle, asset.symbol])
  const handleHover = useCallback(() => onHover(asset.symbol), [onHover, asset.symbol])
  const [editOpen, setEditOpen] = useState(false)
  // resolveIcon returns stable refs from lucide's static icon map.
  const AccentIcon = resolveIcon(accentIcon)

  const menu = renderContextMenu?.({
    asset,
    openEdit: () => setEditOpen(true),
    openNewThesis: () => onNewThesis?.(asset),
  })

  const row = (
        <tr
          className="border-b border-border hover:bg-muted/30 data-[state=open]:bg-muted/30 cursor-pointer group transition-colors"
          onClick={handleToggle}
          onMouseEnter={handleHover}
        >
          <td
            className={`${py} relative pl-2`}
            title={accent ? accentTitle : undefined}
          >
            {accent && (
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 z-10 flex w-[3px] items-center justify-center overflow-hidden transition-[width] duration-200 ease-out group-hover:w-6"
                style={{ backgroundColor: accent }}
              >
                {/* eslint-disable-next-line react-hooks/static-components -- resolveIcon returns stable refs from lucide's icon map */}
                <AccentIcon
                  className="h-3.5 w-3.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100"
                  style={{ color: readableTextColor(accent) }}
                />
              </span>
            )}
            <span
              className={`inline-flex transition-transform duration-200 ease-out ${accent ? "group-hover:translate-x-[18px]" : ""}`}
            >
              {expanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </span>
          </td>
          <td className={`${py} px-3`}>
            <div className="flex items-center gap-2">
              <MarketStatusDot marketState={quote?.market_state} />
              <Link
                to={`/asset/${asset.symbol}`}
                className="font-semibold hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {asset.symbol}
              </Link>
              {settings.show_asset_type_badge && (
                <Badge variant="secondary" className="text-[10px] px-1 py-0">
                  {asset.type}
                </Badge>
              )}
            </div>
          </td>
          {isColumnVisible(columnSettings, "name") && (
            <td className={`${py} px-3 text-sm text-muted-foreground`}>
              <div className="flex items-center gap-2 truncate">
                <span className="truncate">{asset.name}</span>
                {asset.tags.length > 0 && (
                  <span className="flex gap-1 shrink-0">
                    {asset.tags.map((tag) => (
                      <TagBadge key={tag.id} name={tag.name} color={tag.color} />
                    ))}
                  </span>
                )}
              </div>
            </td>
          )}
          {isColumnVisible(columnSettings, "price") && (
            <td className={`${py} px-3 text-right tabular-nums`}>
              <div className="flex items-center justify-end gap-2">
                <QuoteFreshness quote={quote} />
                {priceFmt ? (
                  <span
                    ref={priceRef}
                    className={`font-medium rounded px-1 -mx-1 ${staleClass}`}
                    title={priceFmt.title}
                  >
                    {priceFmt.text}
                  </span>
                ) : (
                  <Skeleton className="h-4 w-14 rounded" />
                )}
              </div>
            </td>
          )}
          {isColumnVisible(columnSettings, "change_pct") && (
            <td className={`${py} px-3 text-right tabular-nums`}>
              {displayPct != null ? (
                <ChangePct
                  ref={pctRef}
                  value={displayPct}
                  className={`font-medium rounded px-1 -mx-1 ${staleClass}`}
                />
              ) : (
                <Skeleton className="h-4 w-12 ml-auto rounded" />
              )}
            </td>
          )}
          {visibleIndicatorFields.map((field) => {
            // Override stale DB volume with live SSE quote values
            if ((field === "volume" || field === "avg_volume") && quote?.[field] != null) {
              const val = quote[field]!
              const desc = getDescriptorByField(field)
              const formatted = desc?.compactFormat ? formatCompactNumber(val) : val.toLocaleString()
              return (
                <td key={field} className={`${py} px-3 text-right text-sm tabular-nums`}>
                  <span title={val.toLocaleString()}>{formatted}</span>
                </td>
              )
            }
            if (field === "macd") {
              const macdVals = extractMacdValues(indicator?.values)
              const m = macdVals?.macd
              const s = macdVals?.macd_signal
              const h = macdVals?.macd_hist
              const hasValues = m != null || s != null || h != null
              const histColor = h != null ? (h >= 0 ? "text-emerald-400" : "text-red-400") : ""
              const fmt = (v: number | null | undefined) =>
                v != null ? v.toFixed(Math.abs(v) >= 100 ? 0 : 2) : "--"
              const histDelta = settings.show_indicator_deltas
                ? formatDeltaAnnotation("macd_hist", indicator?.values)
                : null
              return (
                <td key={field} className={`${py} px-3 text-right text-sm tabular-nums overflow-hidden`}>
                  {hasValues ? (
                    <span className="inline-flex items-center gap-2">
                      <span className="text-muted-foreground">M</span>
                      <span>{fmt(m)}</span>
                      <span className="text-muted-foreground">S</span>
                      <span>{fmt(s)}</span>
                      <span className="text-muted-foreground">H</span>
                      <span className={histColor}>{fmt(h)}</span>
                      {histDelta && (
                        <span className="text-xs">
                          <span className="text-muted-foreground">{histDelta.delta}</span>
                          {histDelta.sigma && <span className="text-amber-500 ml-0.5">⚠ {histDelta.sigma}</span>}
                        </span>
                      )}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">&mdash;</span>
                  )}
                </td>
              )
            }
            // σ-Move is a daily-bar indicator; its stored value reflects the last
            // completed bar (yesterday during market hours), which can contradict
            // the live change % beside it. Recompute it against the live quote so
            // it tracks today. Falls back to the DB value once today's bar syncs.
            const liveVnr = field === "vnr"
              ? computeLiveVnr(quote, indicator?.values, indicator?.close)
              : null
            // When we can't recompute live and fall back to the stored σ-Move,
            // that stored bar may predate the live quote (price sync behind ≥2
            // sessions) — showing it would contradict the live change % beside
            // it. Blank the cell rather than render a wrong-signed number.
            const vnrStale = field === "vnr" && liveVnr == null
              && isStoredVnrStale(quote, indicator?.close)
            // The backend NaN's the stored σ-Move when the bar's return spans a
            // gap in price_history (venue-calendar-verified where the venue is
            // known) and reports the gap width instead — explain the blank
            // rather than leave it mute.
            const vnrGap = field === "vnr" && liveVnr == null
              ? getNumericValue(indicator?.values, "vnr_gap_sessions")
              : null
            const values = liveVnr != null
              ? { ...indicator?.values, vnr: liveVnr }
              : indicator?.values
            const val = getNumericValue(values, field)
            const desc = getDescriptorByField(field)
            // Route through the shared registry formatter so the table matches the
            // card/detail rendering (decimals, threshold colours, currency prefix).
            const formatted = !vnrStale && val != null && desc && values
              ? formatIndicatorField(field, desc, values, asset.currency)
              : null
            return (
              <td key={field} className={`${py} px-3 text-right text-sm tabular-nums`}>
                {formatted ? (
                  <span
                    className={formatted.colorClass}
                    title={desc?.compactFormat && val != null ? val.toLocaleString() : undefined}
                  >
                    {formatted.text}
                  </span>
                ) : (
                  <span
                    className="text-muted-foreground"
                    title={
                      vnrStale
                        ? "σ-Move unavailable — price data is behind the live quote. A background job reconciles this automatically (usually within ~10 min)."
                        : vnrGap != null
                          ? `σ-Move unavailable — the last return spans ${vnrGap} trading sessions (gap in stored price history). A background job backfills missing sessions automatically; see the Stats page.`
                          : undefined
                    }
                  >
                    &mdash;
                  </span>
                )}
              </td>
            )
          })}
        </tr>
  )

  return (
    <>
      {menu ? (
        <ContextMenu>
          <ContextMenuTrigger asChild>{row}</ContextMenuTrigger>
          {menu}
        </ContextMenu>
      ) : (
        row
      )}
      <EditAssetDialog asset={asset} open={editOpen} onOpenChange={setEditOpen} />
      {expanded && (
        <tr>
          <td colSpan={totalColSpan} className="bg-muted/20 p-4 border-b border-border">
            <div className="max-w-[calc(100vw-4rem)]">
              <LazyExpandedChart symbol={asset.symbol} currency={asset.currency} />
            </div>
          </td>
        </tr>
      )}
    </>
  )
})
