import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query"
import { api, type AssetCreate, type AssetUpdate, type SymbolSearchResult } from "../api"
import { keys, STALE_1MIN, STALE_5MIN, useInvalidatingMutation } from "./shared"

export function useAssets() {
  return useQuery({ queryKey: keys.assets, queryFn: api.assets.list, staleTime: STALE_5MIN })
}

/** What is attached to an asset (groups/theses/pseudo-ETFs/tags/note/annotations).
 *  Enabled-gated so it only fetches when the remove dialog is actually open. */
export function useAssetAttachments(symbol: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.assetAttachments(symbol),
    queryFn: () => api.assets.attachments(symbol),
    enabled: enabled && symbol.length > 0,
    staleTime: STALE_1MIN,
  })
}

/** Permanently delete an asset and everything attached to it. Invalidates every
 *  view a membership could have appeared in (groups, listings, theses, pseudo-ETFs). */
export function useHardDeleteAsset() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (symbol: string) => api.assets.hardDelete(symbol),
    onSuccess: () => {
      for (const key of [keys.groups, keys.assets, keys.theses, keys.pseudoEtfs]) {
        qc.invalidateQueries({ queryKey: key })
      }
    },
  })
}

export function useCreateAsset() {
  return useInvalidatingMutation(
    (data: AssetCreate) => api.assets.create(data),
    [keys.assets, keys.groups],
  )
}

export function useUpdateAsset() {
  return useInvalidatingMutation(
    ({ id, data }: { id: number; data: AssetUpdate }) => api.assets.update(id, data),
    [keys.assets, keys.groups],
  )
}

/** Hand an asset's classification fields back to auto-detection. Invalidates
 * the same keys as an edit — it is an edit, just in the other direction. */
export function useResetAssetDetection() {
  return useInvalidatingMutation(
    ({ id, fields }: { id: number; fields?: string[] }) => api.assets.resetDetection(id, fields),
    [keys.assets, keys.groups],
  )
}

// Search
export function useLocalSearch(query: string) {
  return useQuery<SymbolSearchResult[]>({
    queryKey: keys.symbolSearchLocal(query),
    queryFn: () => api.searchLocal(query),
    enabled: query.length >= 1,
    staleTime: STALE_1MIN,
    placeholderData: keepPreviousData,
  })
}
