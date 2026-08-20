import { useMemo } from "react"
import {
  INDICATOR_REGISTRY,
  CATEGORY_ORDER,
  CATEGORY_LABELS,
  isVisibleAt,
  formatIndicatorField,
  formatDeltaAnnotation,
  getSeriesByField,
  type IndicatorDescriptor,
  type IndicatorCategory,
  type Placement,
} from "@/lib/indicator-registry"
import { useSettings } from "@/lib/settings"
import type { Indicator, Quote } from "@/lib/api"

interface StatsPanelProps {
  indicators: Indicator[]
  indicatorVisibility: Record<string, Placement[]>
  currency?: string
  quote?: Quote
}

export function StatsPanel({ indicators, indicatorVisibility, currency, quote }: StatsPanelProps) {
  const { settings } = useSettings()
  const latestValues = useMemo(() => {
    if (!indicators.length) return undefined
    const values = { ...indicators[indicators.length - 1].values }
    // Override stale DB volume with live SSE quote values
    if (quote?.volume != null) values.volume = quote.volume
    if (quote?.avg_volume != null) values.avg_volume = quote.avg_volume
    return values
  }, [indicators, quote])

  const grouped = useMemo(() => {
    const visible = INDICATOR_REGISTRY.filter((d) =>
      isVisibleAt(indicatorVisibility, d.id, "detail_stats"),
    )
    const groups = new Map<IndicatorCategory, IndicatorDescriptor[]>()
    for (const desc of visible) {
      // Hide indicators whose primary field has no data.
      const mainField = desc.series[0]?.field ?? desc.fields[0]
      if (latestValues && latestValues[mainField] == null) continue
      const list = groups.get(desc.category) ?? []
      list.push(desc)
      groups.set(desc.category, list)
    }
    return groups
  }, [indicatorVisibility, latestValues])

  if (!latestValues || grouped.size === 0) return null

  return (
    <div className="rounded-lg border bg-card text-card-foreground divide-y">
      {CATEGORY_ORDER.filter((cat) => grouped.has(cat)).map((cat) => (
        <div key={cat} className="px-4 py-3">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
            {CATEGORY_LABELS[cat]}
          </h3>
          <div className="space-y-2">
            {grouped.get(cat)!.map((desc) => (
              <StatRow
                key={desc.id}
                descriptor={desc}
                values={latestValues}
                currency={currency}
                showDeltas={settings.show_indicator_deltas}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function DeltaBadge({ field, values }: {
  field: string
  values: Record<string, number | string | null | undefined>
}) {
  const ann = formatDeltaAnnotation(field, values)
  if (!ann) return null
  return (
    <span className="text-xs tabular-nums ml-1">
      <span className="text-muted-foreground">{ann.delta}</span>
      {ann.sigma && <span className="text-amber-500 ml-0.5">⚠ {ann.sigma}</span>}
    </span>
  )
}

function StatRow({
  descriptor,
  values,
  currency,
  showDeltas,
}: {
  descriptor: IndicatorDescriptor
  values: Record<string, number | string | null>
  currency?: string
  showDeltas: boolean
}) {
  const mainField = descriptor.series[0]?.field ?? descriptor.fields[0]
  const main = formatIndicatorField(mainField, descriptor, values, currency)
  // Exclude delta/sigma fields from secondary display — they're shown via DeltaBadge
  const secondaryFields = descriptor.fields.filter(
    (f) => f !== mainField && !f.endsWith("_delta") && !f.endsWith("_delta_sigma"),
  )

  // Multi-field indicators: show labeled values
  if (secondaryFields.length > 0) {
    return (
      <div className="space-y-0.5">
        {/* Row 1: label + main value + delta */}
        <div className="flex items-baseline justify-between gap-4">
          <span className="text-sm font-medium">{descriptor.label}</span>
          <span className="flex items-baseline">
            <span className={`text-sm font-semibold tabular-nums ${main.colorClass}`}>{main.text}</span>
            {showDeltas && <DeltaBadge field={mainField} values={values} />}
          </span>
        </div>
        {/* Row 2: description + secondary values */}
        <div className="flex items-baseline justify-between gap-4">
          <p className="text-xs text-muted-foreground">{descriptor.description}</p>
          <div className="flex items-baseline gap-3 tabular-nums shrink-0">
            {secondaryFields.map((f) => {
              const series = getSeriesByField(f)
              const label = series?.label ?? f.replace(/_/g, " ")
              const { text, colorClass } = formatIndicatorField(f, descriptor, values, currency)
              return (
                <span key={f} className="text-xs text-muted-foreground">
                  {label}: <span className={colorClass}>{text}</span>
                  {showDeltas && <DeltaBadge field={f} values={values} />}
                </span>
              )
            })}
          </div>
        </div>
      </div>
    )
  }

  // Single-field indicators: simple two-row layout
  return (
    <div className="space-y-0.5">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-sm font-medium">{descriptor.label}</span>
        <span className="flex items-baseline">
          <span className={`text-sm font-semibold tabular-nums ${main.colorClass}`}>{main.text}</span>
          {showDeltas && <DeltaBadge field={mainField} values={values} />}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{descriptor.description}</p>
    </div>
  )
}
