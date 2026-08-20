import { Link } from "react-router-dom"
import { ArrowLeft, RefreshCw, Plus, FolderPlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { WindowSelector } from "@/components/assets/window-selector"
import { resolveWindow, type AssetWindow } from "@/lib/asset-window"
import { MarketStatusDot } from "@/components/market-status-dot"
import { resolveIcon } from "@/lib/icon-utils"
import { formatAssetPriceWithSettings } from "@/lib/format"
import { ChangePct } from "@/components/change-pct"
import { QuoteFreshness } from "@/components/quote-freshness"
import type { Asset } from "@/lib/api"
import { useActiveAssetDemand, useQuote } from "@/lib/quote-stream"
import { usePriceFlash } from "@/lib/use-price-flash"
import { useRefreshPrices, useCreateAsset, useGroups, useAddAssetsToGroup } from "@/lib/queries"
import { useSettings } from "@/lib/settings"

export type ChartMode = "live" | "historical"

export function Header({
  symbol,
  asset,
  assetWindow,
  setAssetWindow,
  isTracked,
  mode,
  setMode,
}: {
  /** Stays separate from `asset`: this page renders for untracked symbols too,
   * where there is no row yet — that's the whole point of the Track button. */
  symbol: string
  asset?: Asset
  assetWindow: AssetWindow
  setAssetWindow: (w: AssetWindow) => void
  isTracked: boolean
  mode: ChartMode
  setMode: (m: ChartMode) => void
}) {
  const { id: assetId, name } = asset ?? {}
  const { settings } = useSettings()
  const refresh = useRefreshPrices(symbol)
  const createAsset = useCreateAsset()
  const { data: groups } = useGroups()
  const addToGroup = useAddAssetsToGroup()
  useActiveAssetDemand(isTracked ? symbol : undefined)
  const quote = useQuote(symbol.toUpperCase())
  const price = quote?.price ?? null
  const changePct = quote?.change_percent ?? null
  const [priceRef, pctRef] = usePriceFlash(price)
  const priceFmt = price != null
    ? formatAssetPriceWithSettings(price, asset ?? { type: "stock", symbol, currency: "USD" }, {
        compact: settings.compact_numbers,
        group: settings.thousands_separator,
      })
    : null

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Link to="/">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <div className="flex items-center gap-2">
            <MarketStatusDot marketState={quote?.market_state} className="h-2.5 w-2.5" />
            <h1 className="text-2xl font-bold">{symbol}</h1>
          </div>
          {name && <p className="text-sm text-muted-foreground">{name}</p>}
        </div>
        {priceFmt && (
          <span
            ref={priceRef}
            className="text-xl font-semibold tabular-nums rounded px-1"
            title={priceFmt.title}
          >
            {priceFmt.text}
          </span>
        )}
        {changePct != null && (
          <ChangePct
            ref={pctRef}
            value={changePct}
            className="text-sm font-medium rounded px-1"
          />
        )}
        <QuoteFreshness quote={quote} />
        {!isTracked && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => createAsset.mutate({ symbol: symbol.toUpperCase() })}
            disabled={createAsset.isPending}
          >
            <Plus className="h-3.5 w-3.5 mr-1.5" />
            {createAsset.isPending ? "Adding..." : "Track"}
          </Button>
        )}
        {isTracked && assetId != null && groups && (() => {
          const availableGroups = groups.filter(
            (g) => !g.is_default && !g.assets.some((a) => a.id === assetId),
          )
          if (availableGroups.length === 0) return null
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  <FolderPlus className="h-3.5 w-3.5 mr-1.5" />
                  Add to Group
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                {availableGroups.map((g) => {
                  const Icon = resolveIcon(g.icon)
                  return (
                    <DropdownMenuItem
                      key={g.id}
                      onClick={() => addToGroup.mutate({ groupId: g.id, assetIds: [assetId] })}
                    >
                      <Icon className="h-4 w-4" />
                      {g.name}
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          )
        })()}
      </div>
      <div className="flex items-center gap-2">
        <Tabs value={mode} onValueChange={(v) => setMode(v as ChartMode)}>
          <TabsList>
            <TabsTrigger value="live">Live</TabsTrigger>
            <TabsTrigger value="historical">Historical</TabsTrigger>
          </TabsList>
        </Tabs>
        {mode === "historical" && (
          <>
            <WindowSelector value={assetWindow} onChange={setAssetWindow} />
            {isTracked && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => refresh.mutate(resolveWindow(assetWindow).fetchPeriod)}
                disabled={refresh.isPending}
              >
                <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${refresh.isPending ? "animate-spin" : ""}`} />
                Refresh
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
