import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useSettings, type AppSettings, type GroupViewMode } from "@/lib/settings"
import { VisibilityToggle } from "@/components/settings/visibility-toggle"
import { IndicatorVisibilityEditor } from "@/components/settings/indicator-visibility-editor"
import { SymbolSourcesSettings } from "@/components/settings/symbol-sources-settings"

export function SettingsPage() {
  const { settings, updateSettings } = useSettings()
  const [draft, setDraft] = useState<AppSettings>(settings)

  const isDirty = JSON.stringify(draft, (k, v) => k === "_updated_at" ? undefined : v) !==
    JSON.stringify(settings, (k, v) => k === "_updated_at" ? undefined : v)

  const change = (patch: Partial<AppSettings>) => {
    setDraft((prev) => ({ ...prev, ...patch }))
  }

  const apply = () => {
    updateSettings(draft)
  }

  const discard = () => {
    setDraft(settings)
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Group View</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label>Default View</Label>
            <Select
              value={draft.group_view_mode}
              onValueChange={(v) => change({ group_view_mode: v as GroupViewMode })}
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="card">Card</SelectItem>
                <SelectItem value="table">Table</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <VisibilityToggle
            id="wl-sparkline"
            label="Sparkline Chart"
            checked={draft.group_show_sparkline}
            onCheckedChange={(v) => change({ group_show_sparkline: v })}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Chart Preferences</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <VisibilityToggle
            id="sync-crosshairs"
            label="Sync Pseudo-ETF Crosshairs"
            checked={draft.sync_pseudo_etf_crosshairs}
            onCheckedChange={(v) => change({ sync_pseudo_etf_crosshairs: v })}
          />
          <div className="flex items-center justify-between">
            <Label>Default Period</Label>
            <Select
              value={draft.chart_default_period}
              onValueChange={(v) => change({ chart_default_period: v })}
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1mo">1M</SelectItem>
                <SelectItem value="3mo">3M</SelectItem>
                <SelectItem value="6mo">6M</SelectItem>
                <SelectItem value="1y">1Y</SelectItem>
                <SelectItem value="2y">2Y</SelectItem>
                <SelectItem value="5y">5Y</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center justify-between">
            <Label>Chart Type</Label>
            <Select
              value={draft.chart_type}
              onValueChange={(v) => change({ chart_type: v as "candle" | "line" })}
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="candle">Candlestick</SelectItem>
                <SelectItem value="line">Line</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Display</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label>Theme</Label>
            <Select
              value={draft.theme}
              onValueChange={(v) => change({ theme: v as "dark" | "light" | "system" })}
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="system">System</SelectItem>
                <SelectItem value="light">Light</SelectItem>
                <SelectItem value="dark">Dark</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <VisibilityToggle
            id="compact"
            label="Compact Mode"
            checked={draft.compact_mode}
            onCheckedChange={(v) => change({ compact_mode: v })}
          />
          <VisibilityToggle
            id="compact-numbers"
            label="Compact Numbers"
            checked={draft.compact_numbers}
            onCheckedChange={(v) => change({ compact_numbers: v })}
          />
          <VisibilityToggle
            id="thousands-separator"
            label="Thousands Separator"
            checked={draft.thousands_separator}
            onCheckedChange={(v) => change({ thousands_separator: v })}
          />
          <VisibilityToggle
            id="asset-type-badge"
            label="Asset Type Badge"
            checked={draft.show_asset_type_badge}
            onCheckedChange={(v) => change({ show_asset_type_badge: v })}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Indicators</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <VisibilityToggle
            id="indicator-deltas"
            label="Show Daily Deltas"
            checked={draft.show_indicator_deltas}
            onCheckedChange={(v) => change({ show_indicator_deltas: v })}
          />
          <IndicatorVisibilityEditor
            visibility={draft.indicator_visibility}
            onChange={(vis) => change({ indicator_visibility: vis })}
          />
        </CardContent>
      </Card>
      </div>

      <SymbolSourcesSettings />

      {/* Spacer so floating bar doesn't overlap content */}
      {isDirty && <div className="h-16" />}

      {/* Discord-style floating save bar */}
      <div
        className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-lg border bg-card px-4 py-3 shadow-lg transition-all duration-200 ${
          isDirty
            ? "translate-y-0 opacity-100"
            : "translate-y-4 opacity-0 pointer-events-none"
        }`}
      >
        <span className="text-sm text-muted-foreground">You have unsaved changes</span>
        <Button variant="ghost" size="sm" onClick={discard}>
          Reset
        </Button>
        <Button size="sm" onClick={apply}>
          Save Changes
        </Button>
      </div>
    </div>
  )
}
