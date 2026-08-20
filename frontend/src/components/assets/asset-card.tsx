import { memo, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { ContextMenu, ContextMenuTrigger } from "@/components/ui/context-menu"
import { AssetContextMenuContent } from "@/components/assets/asset-context-menu"
import { EditAssetDialog } from "@/components/assets/edit-asset-dialog"
import { NewThesisDialog } from "@/components/thesis/new-thesis-dialog"
import { MarketStatusDot } from "@/components/market-status-dot"
import { useAddAssetToThesis } from "@/lib/queries"
import { DeferredSparkline } from "@/components/chart/sparkline"
import { TagBadge } from "@/components/tags/tag-badge"
import type { Asset, Quote, SparklinePoint, IndicatorSummary } from "@/lib/api"
import { formatAssetPriceWithSettings } from "@/lib/format"
import { ChangePct } from "@/components/change-pct"
import { QuoteFreshness } from "@/components/quote-freshness"
import { getCardDescriptors, isVisibleAt, type IndicatorDescriptor, type Placement } from "@/lib/indicator-registry"
import { IndicatorValue } from "@/components/indicators/indicator-value"
import { usePriceFlash } from "@/lib/use-price-flash"
import { useSettings } from "@/lib/settings"

const CARD_DESCRIPTORS = getCardDescriptors()

export interface AssetCardProps {
  groupId: number
  /** The row itself, not its fields spread out: a new asset field (unit_kind,
   * suggested, whatever comes next) then costs nothing here or in the parent,
   * which is holding the whole Asset anyway. */
  asset: Asset
  quote?: Quote
  sparklineData?: SparklinePoint[]
  indicatorData?: IndicatorSummary
  onDelete: (symbol: string) => void
  onHover: (symbol: string) => void
  showSparkline: boolean
  indicatorVisibility: Record<string, Placement[]>
}

function MiniIndicatorCard({
  descriptor,
  values,
  currency,
  expanded,
  className,
}: {
  descriptor: IndicatorDescriptor
  values?: Record<string, number | string | null>
  currency: string
  expanded?: boolean
  className?: string
}) {
  return (
    <div className={`rounded bg-muted/50 px-2 py-1 ${expanded ? "text-center" : ""} ${className ?? ""}`}>
      <span className="text-[10px] text-muted-foreground">{descriptor.shortLabel}</span>
      <IndicatorValue descriptor={descriptor} values={values} currency={currency} compact expanded={expanded} />
    </div>
  )
}

export const AssetCard = memo(function AssetCard({
  groupId,
  asset,
  quote,
  sparklineData,
  indicatorData,
  onDelete,
  onHover,
  showSparkline,
  indicatorVisibility,
}: AssetCardProps) {
  const { id: assetId, symbol, name, type, currency, tags } = asset
  const { settings } = useSettings()
  const enabledCards = useMemo(
    () => CARD_DESCRIPTORS.filter((d) => isVisibleAt(indicatorVisibility, d.id, "group_card")),
    [indicatorVisibility],
  )
  const lastPrice = quote?.price ?? null
  const changePct = quote?.change_percent ?? null

  const [priceRef, pctRef] = usePriceFlash(lastPrice)
  const [editOpen, setEditOpen] = useState(false)
  const [newThesisOpen, setNewThesisOpen] = useState(false)
  const addToThesis = useAddAssetToThesis()

  const priceFmt = lastPrice != null
    ? formatAssetPriceWithSettings(lastPrice, asset, {
        compact: settings.compact_numbers,
        group: settings.thousands_separator,
      })
    : null

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <Card className="group relative hover:border-primary/50 data-[state=open]:border-primary/50 transition-colors" onMouseEnter={() => onHover(symbol)}>
          <Link to={`/asset/${symbol}`}>
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2">
                <MarketStatusDot marketState={quote?.market_state} />
                <CardTitle className="text-base">{symbol}</CardTitle>
                <Badge variant="secondary" className="text-xs">
                  {type}
                </Badge>
                <div className="ml-auto flex items-center gap-2">
                  <QuoteFreshness quote={quote} />
                  {priceFmt ? (
                    <span
                      ref={priceRef}
                      className="text-base font-semibold tabular-nums rounded px-1 -mx-1"
                      title={priceFmt.title}
                    >
                      {priceFmt.text}
                    </span>
                  ) : (
                    <Skeleton className="h-5 w-16 rounded" />
                  )}
                </div>
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground truncate">{name}</p>
                {changePct != null ? (
                  <ChangePct
                    ref={pctRef}
                    value={changePct}
                    className="text-xs font-medium rounded px-1 -mx-1"
                  />
                ) : (
                  <Skeleton className="h-3.5 w-12 rounded" />
                )}
              </div>
              {tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {tags.map((tag) => (
                    <TagBadge key={tag.id} name={tag.name} color={tag.color} />
                  ))}
                </div>
              )}
            </CardHeader>
            <CardContent className="pt-0 space-y-2">
              {showSparkline && <DeferredSparkline batchData={sparklineData} />}
              {enabledCards.length > 0 && (
                <div
                  className="gap-1.5 mt-1 grid"
                  style={{ gridTemplateColumns: enabledCards.length === 1 ? "1fr" : "1fr 1fr" }}
                >
                  {enabledCards.map((desc, i) => {
                    const isLastOdd = enabledCards.length > 1 && enabledCards.length % 2 === 1 && i === enabledCards.length - 1
                    const isAlone = enabledCards.length === 1
                    return (
                      <MiniIndicatorCard
                        key={desc.id}
                        descriptor={desc}
                        values={indicatorData?.values}
                        currency={currency}
                        expanded={isAlone || isLastOdd}
                        className={isLastOdd ? "col-span-2" : undefined}
                      />
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Link>
        </Card>
      </ContextMenuTrigger>
      <AssetContextMenuContent
        groupId={groupId}
        assetId={assetId}
        symbol={symbol}
        onEdit={() => setEditOpen(true)}
        onRemove={() => onDelete(symbol)}
        onNewThesis={() => setNewThesisOpen(true)}
      />
      <EditAssetDialog
        asset={asset}
        open={editOpen}
        onOpenChange={setEditOpen}
      />
      <NewThesisDialog
        open={newThesisOpen}
        onOpenChange={setNewThesisOpen}
        onCreated={(thesis) => addToThesis.mutate({ thesisId: thesis.id, assetId })}
      />
    </ContextMenu>
  )
})
