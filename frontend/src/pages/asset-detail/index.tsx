import { useState } from "react"
import { useParams } from "react-router-dom"
import { NoteEditor } from "@/components/notes/note-editor"
import { AnnotationsList } from "@/components/notes/annotations-list"
import { TagInput } from "@/components/tags/tag-input"
import { ThesisInput } from "@/components/thesis/thesis-input"
import {
  useAssets,
  useAssetWindow,
  useAnnotations,
  useCreateAnnotation,
  useDeleteAnnotation,
  useNote,
  useUpdateNote,
} from "@/lib/queries"
import type { AssetWindow } from "@/lib/asset-window"
import { useSettings } from "@/lib/settings"
import { useQuote } from "@/lib/quote-stream"
import { StatsPanel } from "@/components/assets/stats-panel"
import { Header, type ChartMode } from "./header"
import { ChartSection } from "./chart-section"
import { MovementStats } from "./movement-stats"


export function AssetDetailPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const { settings } = useSettings()
  const [assetWindow, setAssetWindow] = useState<AssetWindow>({
    kind: "period",
    period: settings.chart_default_period,
  })
  const [mode, setMode] = useState<ChartMode>("historical")
  const { data: assets } = useAssets()
  const asset = assets?.find((a) => a.symbol === symbol?.toUpperCase())
  const { prices, indicators, windowLabel } = useAssetWindow(symbol ?? "", assetWindow, {
    enabled: !!symbol && mode !== "live",
  })
  const quote = useQuote(symbol?.toUpperCase() ?? "")
  const isTracked = !!asset

  if (!symbol) return null

  return (
    <div className="p-6 space-y-6">
      <Header symbol={symbol} asset={asset} assetWindow={assetWindow} setAssetWindow={setAssetWindow} isTracked={isTracked} mode={mode} setMode={setMode} />
      <ChartSection
        symbol={symbol}
        assetWindow={assetWindow}
        indicatorVisibility={settings.indicator_visibility}
        chartType={settings.chart_type}
        currency={asset?.currency}
        assetType={asset?.type}
        mode={mode}
      />
      {mode === "historical" && prices && prices.length > 1 && (
        <MovementStats
          prices={prices}
          label={windowLabel}
          symbol={symbol}
          asset={asset}
        />
      )}
      {mode === "historical" && indicators && indicators.length > 0 && (
        <StatsPanel
          indicators={indicators}
          indicatorVisibility={settings.indicator_visibility}
          currency={asset?.currency}
          quote={quote}
        />
      )}
      {isTracked && (
        <>
          <TagInput symbol={symbol} currentTags={asset?.tags ?? []} />
          {asset && <ThesisInput assetId={asset.id} />}
          <AssetAnnotations symbol={symbol} />
          <AssetNote symbol={symbol} />
        </>
      )}
    </div>
  )
}

function AssetAnnotations({ symbol }: { symbol: string }) {
  const { data: annotations } = useAnnotations(symbol)
  const create = useCreateAnnotation(symbol)
  const remove = useDeleteAnnotation(symbol)
  return (
    <AnnotationsList
      annotations={annotations}
      onCreate={create.mutate}
      onDelete={remove.mutate}
      isCreating={create.isPending}
    />
  )
}

function AssetNote({ symbol }: { symbol: string }) {
  const { data: note } = useNote(symbol)
  const update = useUpdateNote(symbol)
  return <NoteEditor note={note} onSave={update.mutate} isSaving={update.isPending} />
}
