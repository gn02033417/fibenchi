import type { Quote } from "@/lib/api"
import { formatQuoteUpdatedAt } from "@/lib/format"

type QuoteFreshnessSource = Pick<Quote, "data_status" | "updated_at">

const STATUS_CLASSES = {
  LIVE: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  CACHED: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  DISCONNECTED: "border-muted-foreground/30 bg-muted text-muted-foreground",
} as const

export function QuoteFreshness({
  quote,
  className,
}: {
  quote?: QuoteFreshnessSource
  className?: string
}) {
  const status = quote?.data_status
  if (!status) return null

  const updatedAt = status === "LIVE" ? null : formatQuoteUpdatedAt(quote.updated_at)
  const label = updatedAt
    ? `${status} · Last updated ${updatedAt}`
    : status === "LIVE"
      ? status
      : `${status} · Last update unavailable`

  return (
    <span
      data-quote-status={status}
      title={label}
      className={`inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-[10px] font-medium leading-none ${STATUS_CLASSES[status]} ${className ?? ""}`}
    >
      {label}
    </span>
  )
}
