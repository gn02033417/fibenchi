import { useCallback, useState, useMemo, useTransition } from "react"
import { Activity, ArrowDownAZ, ArrowUpAZ, Layers, LayoutGrid, List, Magnet, Pencil, ScanLine, Star, Table, TrendingUp } from "lucide-react"
import { resolveIcon } from "@/lib/icon-utils"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { SegmentedControl } from "@/components/ui/segmented-control"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { AddSymbolDialog } from "@/components/assets/add-symbol-dialog"
import { RemoveAssetDialog } from "@/components/assets/remove-asset-dialog"
import { AssetCard } from "@/components/assets/asset-card"
import { TagFilterPopover } from "@/components/tags/tag-filter-popover"
import { useGroup, useGroups, useGroupSparklines, useGroupIndicators, useUpdateGroup, useTags, useTheses, usePrefetchAssetDetail, usePrefetchOtherGroups } from "@/lib/queries"
import { useActiveGroupDemand, useQuotes } from "@/lib/quote-stream"
import { buildSortOptions, getScannableDescriptors } from "@/lib/indicator-registry"
import { useSettings, type AssetTypeFilter, type GroupSortBy, type GroupViewMode, type SortDir } from "@/lib/settings"
import { useFilteredSortedAssets, getSortValue, compareSortValues, type SortValue } from "@/lib/use-group-filter"
import type { Asset, Thesis } from "@/lib/api"
import { GroupTable } from "@/components/group-table"
import { AssetContextMenuContent } from "@/components/assets/asset-context-menu"
import { ThesisGroupedTable } from "@/components/thesis/thesis-grouped-table"
import { CrosshairTimeSyncProvider } from "@/components/chart/crosshair-time-sync"
import { ScannerView } from "@/components/scanner-view"
import { LiveDayView } from "@/components/chart/live-day-view"

const SCANNABLE_DESCRIPTORS = getScannableDescriptors()

const SORT_OPTIONS = buildSortOptions()

const SORT_LABELS: Record<string, string> = Object.fromEntries(SORT_OPTIONS)

export function GroupPage({ groupId }: { groupId: number }) {
  const { data: group, isLoading: groupLoading } = useGroup(groupId)
  const { data: allTags } = useTags()
  const { data: theses } = useTheses()
  const { data: allGroups } = useGroups()
  const [removeTarget, setRemoveTarget] = useState<Asset | null>(null)
  const [selectedTags, setSelectedTags] = useState<number[]>([])
  const [sparklinePeriod, setSparklinePeriod] = useState("3mo")
  const { settings, updateSettings } = useSettings()
  const thesisGrouping = settings.thesis_grouping
  const thesisCluster = settings.thesis_cluster
  const [isPending, startTransition] = useTransition()
  // settings.group_view_mode = immediate (drives SegmentedControl highlight)
  // viewMode = deferred via useTransition (drives content rendering)
  const [deferredViewMode, setDeferredViewMode] = useState(settings.group_view_mode)
  const viewMode = deferredViewMode
  const setViewMode = (v: GroupViewMode) => {
    updateSettings({ group_view_mode: v })
    startTransition(() => {
      setDeferredViewMode(v)
    })
  }
  const [scannerIndicator, setScannerIndicator] = useState("macd")
  const [scannerPeriod, setScannerPeriod] = useState(settings.chart_default_period)
  // Sparklines only render on cards, so only fetch them in card view.
  const { data: batchSparklines } = useGroupSparklines(groupId, sparklinePeriod, viewMode === "card")
  const { data: batchIndicators } = useGroupIndicators(groupId)
  const prefetch = usePrefetchAssetDetail(settings.chart_default_period)
  usePrefetchOtherGroups(groupId, sparklinePeriod)

  const typeFilter = settings.group_type_filter
  const sortBy = settings.group_sort_by
  const sortDir = settings.group_sort_dir

  const quotes = useQuotes()
  useActiveGroupDemand(groupId)

  const allAssets = group?.assets
  const isDefaultGroup = group?.is_default ?? false

  const assets = useFilteredSortedAssets(allAssets, {
    typeFilter,
    selectedTags,
    sortBy,
    sortDir,
    quotes,
    indicators: batchIndicators,
  })

  // List view always paints each row's left border with its thesis colour. When the
  // "keep together" toggle is on, members are additionally clustered: each thesis's
  // rows are pulled into a block ordered *within* by the active sort, and the block is
  // placed in the global order by the AVERAGE of its members' metric, interleaved with
  // ungrouped assets (each a size-1 unit). Off → plain sort, just colour-edged.
  const { listAssets, accentColors, accentTitles, accentIcons } = useMemo(() => {
    if (thesisGrouping !== "list" || !theses || theses.length === 0 || !assets) {
      return { listAssets: assets, accentColors: undefined, accentTitles: undefined, accentIcons: undefined }
    }
    // asset id -> theses containing it, in the API's order (alphabetical by name)
    const thesesByAssetId = new Map<number, Thesis[]>()
    for (const t of theses) {
      for (const m of t.assets) {
        const list = thesesByAssetId.get(m.id)
        if (list) list.push(t)
        else thesesByAssetId.set(m.id, [t])
      }
    }

    // Colour edges + tooltips + hover icon are shown whether or not clustering is on.
    const colors: Record<string, string> = {}
    const titles: Record<string, string> = {}
    const icons: Record<string, string> = {}
    for (const a of assets) {
      const ts = thesesByAssetId.get(a.id)
      if (ts && ts.length > 0) {
        colors[a.symbol] = ts[0].color
        titles[a.symbol] = ts.map((t) => t.name).join(", ")
        icons[a.symbol] = ts[0].icon ?? "briefcase"
      }
    }

    if (!thesisCluster) {
      return { listAssets: assets, accentColors: colors, accentTitles: titles, accentIcons: icons }
    }

    // A unit is one sortable entry of the global order: a thesis block (many rows) or
    // a lone ungrouped asset (one row). `numVals` accumulates members' numeric metric
    // for the block average. Units are created in first-appearance order (stable ties).
    type Unit = { key: SortValue; rows: Asset[]; numVals: number[] }
    const units: Unit[] = []
    const blockByThesisId = new Map<number, Unit>()

    for (const a of assets) {
      const val = getSortValue(a, sortBy, quotes, batchIndicators)
      const ts = thesesByAssetId.get(a.id)
      if (!ts || ts.length === 0) {
        units.push({ key: val, rows: [a], numVals: [] })
        continue
      }
      let block = blockByThesisId.get(ts[0].id)
      if (!block) {
        block = { key: null, rows: [], numVals: [] }
        blockByThesisId.set(ts[0].id, block)
        units.push(block)
      }
      block.rows.push(a) // assets are pre-sorted, so within-block order is the active sort
      if (typeof val === "number") block.numVals.push(val)
    }

    // Block key = average of members' metric (numeric sorts); for the "name" sort the
    // average is meaningless, so the leading member (in the current direction) stands in.
    for (const block of blockByThesisId.values()) {
      block.key =
        sortBy === "name"
          ? block.rows.length
            ? getSortValue(block.rows[0], sortBy, quotes, batchIndicators)
            : null
          : block.numVals.length
            ? block.numVals.reduce((s, v) => s + v, 0) / block.numVals.length
            : null
    }

    const dir = sortDir === "asc" ? 1 : -1
    const ordered = [...units]
      .sort((x, y) => dir * compareSortValues(x.key, y.key))
      .flatMap((u) => u.rows)

    return { listAssets: ordered, accentColors: colors, accentTitles: titles, accentIcons: icons }
  }, [thesisGrouping, thesisCluster, theses, assets, sortBy, sortDir, quotes, batchIndicators])

  const setTypeFilter = (v: AssetTypeFilter) =>
    updateSettings({ group_type_filter: v })

  const handleSort = (key: GroupSortBy) => {
    if (sortBy === key) {
      updateSettings({ group_sort_dir: sortDir === "asc" ? "desc" : "asc" })
    } else {
      const defaultDir: SortDir = key === "name" ? "asc" : "desc"
      updateSettings({ group_sort_by: key, group_sort_dir: defaultDir })
    }
  }

  const handleRemove = useCallback((symbol: string) => {
    const asset = allAssets?.find((a) => a.symbol === symbol)
    if (asset) setRemoveTarget(asset)
  }, [allAssets])

  const toggleTag = (id: number) =>
    setSelectedTags((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]
    )

  return (
    <div className="p-4 lg:p-6 space-y-4 lg:space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <GroupHeader groupId={groupId} group={group} isDefaultGroup={isDefaultGroup} />
          {/* Type filter */}
          <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as AssetTypeFilter)}>
            <SelectTrigger className="h-7! py-0 text-xs" aria-label="Filter by asset type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="stock">Stocks</SelectItem>
              <SelectItem value="etf">ETFs</SelectItem>
              <SelectItem value="index">Indices</SelectItem>
            </SelectContent>
          </Select>
          {viewMode === "scanner" ? (
            <>
              {/* Indicator selector */}
              <Select value={scannerIndicator} onValueChange={setScannerIndicator}>
                <SelectTrigger className="h-7! py-0 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCANNABLE_DESCRIPTORS.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.shortLabel}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {/* Period selector */}
              <SegmentedControl
                options={[
                  { value: "1mo", label: "1M" },
                  { value: "3mo", label: "3M" },
                  { value: "6mo", label: "6M" },
                  { value: "1y", label: "1Y" },
                  { value: "2y", label: "2Y" },
                  { value: "5y", label: "5Y" },
                ]}
                value={scannerPeriod}
                onChange={setScannerPeriod}
              />
            </>
          ) : viewMode === "live" ? null : (
            <>
              {/* Sparkline period — only drives the card-view mini-charts */}
              {viewMode === "card" && (
                <SegmentedControl
                  options={[
                    { value: "3mo", label: "3M" },
                    { value: "6mo", label: "6M" },
                    { value: "1y", label: "1Y" },
                  ]}
                  value={sparklinePeriod}
                  onChange={setSparklinePeriod}
                />
              )}
              {/* Sort */}
              <div className="flex items-center gap-1">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5">
                      {sortDir === "asc" ? <ArrowUpAZ className="h-3.5 w-3.5" /> : <ArrowDownAZ className="h-3.5 w-3.5" />}
                      {SORT_LABELS[sortBy]}
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    {SORT_OPTIONS.map(([key, label]) => (
                      <DropdownMenuItem key={key} onClick={() => handleSort(key)}>
                        {label}
                        {sortBy === key && (
                          <span className="ml-auto text-muted-foreground text-xs">
                            {sortDir === "asc" ? "\u2191" : "\u2193"}
                          </span>
                        )}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </>
          )}
          {/* View mode */}
          <Select value={settings.group_view_mode} onValueChange={(v) => setViewMode(v as GroupViewMode)}>
            <SelectTrigger className="h-7! py-0 text-xs" aria-label="View mode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="table"><span className="flex items-center gap-2"><Table className="h-3.5 w-3.5" />Table</span></SelectItem>
              <SelectItem value="card"><span className="flex items-center gap-2"><LayoutGrid className="h-3.5 w-3.5" />Cards</span></SelectItem>
              <SelectItem value="live"><span className="flex items-center gap-2"><Activity className="h-3.5 w-3.5" />Live</span></SelectItem>
              <SelectItem value="scanner"><span className="flex items-center gap-2"><ScanLine className="h-3.5 w-3.5" />Indicators</span></SelectItem>
            </SelectContent>
          </Select>
          {viewMode === "table" && (
            <div className="flex items-center gap-1.5">
              <SegmentedControl
                options={[
                  { value: "list", label: <List className="h-3.5 w-3.5" />, title: "List — colour-edged by thesis" },
                  { value: "sections", label: <Layers className="h-3.5 w-3.5" />, title: "Group by thesis — sections" },
                ]}
                value={thesisGrouping}
                onChange={(v) => updateSettings({ thesis_grouping: v })}
              />
              {thesisGrouping === "list" && (
                <Button
                  variant={thesisCluster ? "default" : "outline"}
                  size="sm"
                  className="h-7 gap-1.5 text-xs"
                  onClick={() => updateSettings({ thesis_cluster: !thesisCluster })}
                  title="Sort each thesis's members together as one block"
                >
                  <Magnet className="h-3.5 w-3.5" />
                  Sort together
                </Button>
              )}
            </div>
          )}
          {allTags && allTags.length > 0 && (
            <TagFilterPopover
              tags={allTags}
              selectedTags={selectedTags}
              onToggleTag={toggleTag}
              onClear={() => setSelectedTags([])}
            />
          )}
        </div>
        <AddSymbolDialog groupId={groupId} />
      </div>

      {groupLoading && <p className="text-muted-foreground">Loading...</p>}

      {assets && assets.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
          <TrendingUp className="h-12 w-12 mb-4" />
          <p>
            {allAssets && allAssets.length > 0
              ? "No assets match the current filters."
              : "No assets yet. Add a symbol above to get started."}
          </p>
        </div>
      )}

      <div className={isPending ? "opacity-70 transition-opacity" : "transition-opacity"}>
      {viewMode === "live" && assets && assets.length > 0 ? (
        <LiveDayView assets={assets} quotes={quotes} indicators={batchIndicators} />
      ) : viewMode === "scanner" && assets && assets.length > 0 ? (
        <CrosshairTimeSyncProvider enabled={true}>
          <ScannerView assets={assets} descriptorId={scannerIndicator} period={scannerPeriod} />
        </CrosshairTimeSyncProvider>
      ) : viewMode === "table" && assets && assets.length > 0 ? (
        <CrosshairTimeSyncProvider enabled={true}>
          {thesisGrouping === "sections" ? (
            <ThesisGroupedTable
              groupId={groupId}
              assets={assets}
              theses={theses ?? []}
              allGroups={allGroups ?? []}
              quotes={quotes}
              indicators={batchIndicators}
              onDelete={handleRemove}
              compactMode={settings.compact_mode}
              onHover={prefetch}
              sortBy={sortBy}
              sortDir={sortDir}
              onSort={handleSort}
            />
          ) : (
            <GroupTable
              assets={listAssets ?? assets}
              quotes={quotes}
              indicators={batchIndicators}
              compactMode={settings.compact_mode}
              onHover={prefetch}
              sortBy={sortBy}
              sortDir={sortDir}
              onSort={handleSort}
              accentColors={accentColors}
              accentTitles={accentTitles}
              accentIcons={accentIcons}
              renderContextMenu={({ asset, openEdit, openNewThesis }) => (
                <AssetContextMenuContent
                  groupId={groupId}
                  assetId={asset.id}
                  symbol={asset.symbol}
                  onEdit={openEdit}
                  onNewThesis={openNewThesis}
                  onRemove={() => handleRemove(asset.symbol)}
                />
              )}
            />
          )}
        </CrosshairTimeSyncProvider>
      ) : (
        <div className={`grid gap-4 ${
          settings.compact_mode
            ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5"
            : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
        }`}>
          {assets?.map((asset) => (
            <AssetCard
              key={asset.id}
              groupId={groupId}
              asset={asset}
              quote={quotes[asset.symbol]}
              sparklineData={batchSparklines?.[asset.symbol]}
              indicatorData={batchIndicators?.[asset.symbol]}
              onDelete={handleRemove}
              onHover={prefetch}
              showSparkline={settings.group_show_sparkline}
              indicatorVisibility={settings.indicator_visibility}
            />
          ))}
        </div>
      )}
      </div>

      <RemoveAssetDialog
        asset={removeTarget}
        groupId={groupId}
        groupName={group?.name ?? "this group"}
        open={removeTarget !== null}
        onOpenChange={(o) => {
          if (!o) setRemoveTarget(null)
        }}
      />
    </div>
  )
}

function GroupHeader({ groupId, group, isDefaultGroup }: {
  groupId: number
  group?: { name: string; description: string | null; icon: string | null; assets: { id: number }[] }
  isDefaultGroup: boolean
}) {
  const updateGroup = useUpdateGroup()
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState("")

  const HeaderIcon = useMemo(
    () => isDefaultGroup ? Star : resolveIcon(group?.icon),
    [isDefaultGroup, group?.icon],
  )

  const startEditing = () => {
    if (isDefaultGroup || !group) return
    setEditName(group.name)
    setEditing(true)
  }

  const saveEdit = () => {
    const name = editName.trim()
    if (!name || name === group?.name) {
      setEditing(false)
      return
    }
    updateGroup.mutate(
      { id: groupId, data: { name } },
      { onSuccess: () => setEditing(false) },
    )
  }

  if (!group) {
    return <Skeleton className="h-8 w-40" />
  }

  if (editing) {
    return (
      <Input
        value={editName}
        onChange={(e) => setEditName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") saveEdit()
          if (e.key === "Escape") setEditing(false)
        }}
        onBlur={saveEdit}
        autoFocus
        className="h-9 w-48 text-xl font-bold"
      />
    )
  }

  return (
    <div className="flex items-center gap-2">
      {/* eslint-disable-next-line react-hooks/static-components -- resolveIcon returns stable refs from lucide's icon map */}
      <HeaderIcon className="h-5 w-5 text-muted-foreground" />
      <h1 className="text-2xl font-bold">{group.name}</h1>
      {!isDefaultGroup && (
        <button
          onClick={startEditing}
          className="text-muted-foreground hover:text-foreground transition-colors"
          title="Rename group"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      )}
      <span className="text-sm text-muted-foreground">
        {group.assets.length} {group.assets.length === 1 ? "asset" : "assets"}
      </span>
    </div>
  )
}
