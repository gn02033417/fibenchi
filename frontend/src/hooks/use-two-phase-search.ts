import { useLocalSearch } from "@/lib/queries"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import type { SymbolSearchResult } from "@/lib/api"

export interface TwoPhaseSearchResult {
  localResults: SymbolSearchResult[] | undefined
  allResults: SymbolSearchResult[]
}

/**
 * Taiwan symbol search against the local directory with a short debounce.
 */
export function useTwoPhaseSearch(query: string): TwoPhaseSearchResult {
  const localQuery = useDebouncedValue(query, 100)
  const { data: localResults } = useLocalSearch(localQuery)
  return { localResults, allResults: localResults ?? [] }
}
