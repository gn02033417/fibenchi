import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query"
import { useCallback, useMemo } from "react"
import { api } from "../api"
import { resolveWindow, type AssetWindow } from "../asset-window"
import { keys, STALE_5MIN, useInvalidatingMutation } from "./shared"

export function useAssetDetail(symbol: string, period?: string, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: keys.assetDetail(symbol, period),
    queryFn: () => api.prices.detail(symbol, period),
    enabled: (opts?.enabled ?? true) && !!symbol,
    staleTime: STALE_5MIN, // 5 min — daily OHLCV data, SSE handles live quotes
    placeholderData: keepPreviousData,
  })
}

function sliceFrom<T extends { date: string }>(
  rows: T[] | undefined,
  startDate: string | null,
): T[] | undefined {
  if (!rows || !startDate) return rows
  return rows.filter((r) => r.date >= startDate) // ISO dates compare lexicographically
}

/**
 * Fetch asset detail for an analysis window. Resolves the window to a covering
 * fixed period (so the underlying `useAssetDetail` cache is shared with the
 * chart), then slices prices + indicators to the window's exact start.
 *
 * Consumers should read the sliced `prices` / `indicators` returned here — NOT
 * `data.prices` (which is the unsliced full-period payload). `windowEmpty` is
 * true when the fetch returned data but nothing falls inside the window (e.g.
 * a "since" date with no trading days yet), so callers can distinguish that
 * from "the asset has no data at all".
 */
export function useAssetWindow(symbol: string, assetWindow: AssetWindow, opts?: { enabled?: boolean }) {
  const { fetchPeriod, startDate, label } = resolveWindow(assetWindow)
  const query = useAssetDetail(symbol, fetchPeriod, opts)
  const prices = useMemo(() => sliceFrom(query.data?.prices, startDate), [query.data?.prices, startDate])
  const indicators = useMemo(
    () => sliceFrom(query.data?.indicators, startDate),
    [query.data?.indicators, startDate],
  )
  const windowEmpty = !!query.data?.prices?.length && !prices?.length
  return { ...query, prices, indicators, fetchPeriod, windowLabel: label, windowEmpty }
}

export function useRefreshPrices(symbol: string) {
  return useInvalidatingMutation(
    (period?: string) => api.prices.refresh(symbol, period),
    [["asset-detail", symbol]],
  )
}

// Prefetch — fire on hover to warm cache before navigation
export function usePrefetchAssetDetail(period: string) {
  const qc = useQueryClient()
  return useCallback(
    (symbol: string) =>
      qc.prefetchQuery({
        queryKey: keys.assetDetail(symbol, period),
        queryFn: () => api.prices.detail(symbol, period),
        staleTime: STALE_5MIN,
      }),
    [qc, period],
  )
}
