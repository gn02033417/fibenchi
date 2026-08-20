import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react"
import { INDICATOR_REGISTRY, type Placement } from "@/lib/indicator-registry"
import { api } from "@/lib/api"

export type AssetTypeFilter = "all" | "stock" | "etf" | "index"
export type GroupSortBy = string
export type SortDir = "asc" | "desc"
export type MacdStyle = "classic" | "divergence"
export type GroupViewMode = "card" | "table" | "scanner" | "live"
/** Thesis layout in the table view: a flat (colour-edged) list or per-thesis sections. */
export type ThesisGrouping = "list" | "sections"

export interface AppSettings {
  /** Per-indicator placement visibility matrix. Missing key = use descriptor defaults. */
  indicator_visibility: Record<string, Placement[]>
  group_macd_style: MacdStyle
  group_show_sparkline: boolean
  group_view_mode: GroupViewMode
  group_type_filter: AssetTypeFilter
  group_sort_by: GroupSortBy
  group_sort_dir: SortDir
  group_table_columns: Record<string, boolean>
  group_table_column_widths: Record<string, number>
  /** Left-to-right order of indicator columns (field ids). Empty = registry order. */
  group_table_column_order: string[]
  thesis_grouping: ThesisGrouping
  /** In list view, keep a thesis's members together when sorting (average-and-interleave). */
  thesis_cluster: boolean
  chart_default_period: string
  chart_type: "candle" | "line"
  theme: "dark" | "light" | "system"
  compact_mode: boolean
  compact_numbers: boolean
  show_asset_type_badge: boolean
  decimal_places: number
  sync_pseudo_etf_crosshairs: boolean
  show_indicator_deltas: boolean
  thousands_separator: boolean
  _updated_at?: number
}

/**
 * Migrate old boolean visibility maps to the new placement-based system.
 * Only indicators explicitly turned off get entries; the rest fall through to defaults.
 */
function migrateOldVisibility(
  groupVis?: Record<string, boolean>,
  detailVis?: Record<string, boolean>,
): Record<string, Placement[]> {
  const result: Record<string, Placement[]> = {}
  for (const desc of INDICATOR_REGISTRY) {
    const groupOff = groupVis?.[desc.id] === false
    const detailOff = detailVis?.[desc.id] === false
    if (!groupOff && !detailOff) continue
    let placements = [...desc.defaults]
    if (groupOff) placements = placements.filter((p) => !p.startsWith("group_"))
    if (detailOff) placements = placements.filter((p) => !p.startsWith("detail_"))
    result[desc.id] = placements
  }
  return result
}

/**
 * Migrate the old boolean `group_by_thesis` toggle to the 3-way `thesis_grouping`
 * selector: `true` → sectioned grouping, `false`/absent → no grouping. Only fills
 * `thesis_grouping` when it isn't already set, so an explicit choice (including the
 * new "inline" color-coded mode) is never clobbered by a stale boolean.
 */
/**
 * Normalize legacy thesis settings into the current shape
 * ({ thesis_grouping: "list" | "sections", thesis_cluster }):
 *   - boolean `group_by_thesis`: true → sections, false → list
 *   - old 3-way `thesis_grouping`: "none" → list, "inline" → list + cluster, "sections" → sections
 * Only fills what it can derive; DEFAULT_SETTINGS backfills the rest, and a value
 * already in the new shape is left untouched.
 */
function migrateThesisSettings(s: Record<string, unknown>): Partial<AppSettings> {
  const out: Record<string, unknown> = { ...s }
  const tg = out.thesis_grouping
  if (tg === "none" || tg === "inline") {
    out.thesis_cluster = tg === "inline"
    out.thesis_grouping = "list"
  } else if (tg == null && "group_by_thesis" in out) {
    out.thesis_grouping = out.group_by_thesis ? "sections" : "list"
  }
  delete out.group_by_thesis
  return out as Partial<AppSettings>
}

// eslint-disable-next-line react-refresh/only-export-components
export const DEFAULT_SETTINGS: AppSettings = {
  indicator_visibility: {},
  group_macd_style: "divergence",
  group_show_sparkline: true,
  group_view_mode: "card",
  group_type_filter: "all",
  group_sort_by: "name",
  group_sort_dir: "asc",
  group_table_columns: {},
  group_table_column_widths: {},
  group_table_column_order: [],
  thesis_grouping: "list",
  thesis_cluster: false,
  chart_default_period: "1y",
  chart_type: "candle",
  theme: "system",
  compact_mode: false,
  compact_numbers: false,
  show_asset_type_badge: true,
  decimal_places: 2,
  sync_pseudo_etf_crosshairs: false,
  show_indicator_deltas: true,
  thousands_separator: true,
}


const STORAGE_KEY = "fibenchi-settings"

function loadFromStorage(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      // Migrate old boolean visibility maps to new placement-based system
      if ("group_indicator_visibility" in parsed || "detail_indicator_visibility" in parsed) {
        parsed.indicator_visibility = migrateOldVisibility(
          parsed.group_indicator_visibility,
          parsed.detail_indicator_visibility,
        )
        delete parsed.group_indicator_visibility
        delete parsed.detail_indicator_visibility
        // Persist migrated settings
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...DEFAULT_SETTINGS, ...migrateThesisSettings(parsed) }))
      }
      // Migrate before merging defaults so legacy thesis values aren't masked.
      return { ...DEFAULT_SETTINGS, ...migrateThesisSettings(parsed) }
    }
  } catch {
    // ignore corrupt storage
  }
  return { ...DEFAULT_SETTINGS }
}

function saveToStorage(settings: AppSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}

interface SettingsContextValue {
  settings: AppSettings
  updateSettings: (patch: Partial<AppSettings>) => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(loadFromStorage)

  // On mount: fetch from backend and merge (newer timestamp wins)
  useEffect(() => {
    let cancelled = false

    api.settings
      .get()
      .then((body) => {
        if (cancelled) return
        if (body?.data && Object.keys(body.data).length > 0) {
          const remoteData = migrateThesisSettings(body.data)
          setSettings((prev) => {
            const localTs = prev._updated_at
            const remoteTs = remoteData._updated_at
            // Only let backend overwrite if it has a newer (or equal) timestamp,
            // or if local has no timestamp yet (first sync)
            if (localTs && remoteTs && remoteTs < localTs) {
              // Local is newer — push it to backend to reconcile
              api.settings.update(prev as unknown as Record<string, unknown>).catch(() => {})
              return prev
            }
            const merged = { ...prev, ...remoteData }
            saveToStorage(merged)
            return merged
          })
        }
      })
      .catch(() => {
        // backend unavailable — use local settings
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Apply theme
  useEffect(() => {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)")
    const apply = () => {
      const isDark =
        settings.theme === "dark" || (settings.theme === "system" && prefersDark.matches)
      document.documentElement.classList.toggle("dark", isDark)
    }
    apply()

    if (settings.theme === "system") {
      prefersDark.addEventListener("change", apply)
      return () => prefersDark.removeEventListener("change", apply)
    }
  }, [settings.theme])

  const updateSettings = useCallback((patch: Partial<AppSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch, _updated_at: Date.now() }
      saveToStorage(next)
      // Fire-and-forget backend sync
      api.settings.update(next as unknown as Record<string, unknown>).catch(() => {})
      return next
    })
  }, [])

  return (
    <SettingsContext.Provider value={{ settings, updateSettings }}>
      {children}
    </SettingsContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error("useSettings must be used within SettingsProvider")
  return ctx
}
