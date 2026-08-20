interface QuoteStreamParams {
  intradaySymbols?: Iterable<string>
  activeAssets?: Iterable<string>
  activeGroupIds?: Iterable<number>
}

function uniqueSortedSymbols(symbols: Iterable<string>): string[] {
  return [...new Set([...symbols].map((symbol) => symbol.trim().toUpperCase()).filter(Boolean))].sort()
}

function uniqueSortedGroupIds(groupIds: Iterable<number>): number[] {
  return [...new Set([...groupIds].filter((groupId) => Number.isInteger(groupId) && groupId > 0))]
    .sort((left, right) => left - right)
}

/** Build the one SSE URL from all mounted views' demand declarations. */
export function buildQuoteStreamUrl({
  intradaySymbols = [],
  activeAssets = [],
  activeGroupIds = [],
}: QuoteStreamParams = {}): string {
  const params = new URLSearchParams()
  const intraday = uniqueSortedSymbols(intradaySymbols)
  const assets = uniqueSortedSymbols(activeAssets)
  const groups = uniqueSortedGroupIds(activeGroupIds)
  if (intraday.length > 0) params.set("intraday", intraday.join(","))
  if (assets.length > 0) params.set("active_asset", assets.join(","))
  if (groups.length > 0) params.set("active_group", groups.join(","))
  const query = params.toString()
  return query ? `/api/quotes/stream?${query}` : "/api/quotes/stream"
}
