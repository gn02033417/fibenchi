import { SearchResultItem } from "@/components/search/search-result-item"
import { useTrackedSymbols } from "@/hooks/use-tracked-symbols"
import type { SymbolSearchResult } from "@/lib/api"

interface SearchResultsListProps {
  allResults: SymbolSearchResult[]
  /** Currently highlighted index for keyboard navigation (-1 = none). */
  selectedIndex?: number
  onSelect: (result: SymbolSearchResult) => void
  onHover?: (index: number) => void
  /** Extra class name for each row button. */
  rowClassName?: string
  /** Fixed width class for the symbol column. */
  symbolClassName?: string
}

/**
 * Shared Taiwan symbol-directory search result list.
 */
export function SearchResultsList({
  allResults,
  selectedIndex = -1,
  onSelect,
  onHover,
  rowClassName = "px-4 py-2.5",
  symbolClassName,
}: SearchResultsListProps) {
  const trackedSymbols = useTrackedSymbols()

  return (
    <>
      {allResults.map((r, i) => {
        const isTracked = trackedSymbols.has(r.symbol)
        return (
          <div key={r.symbol}>
            <button
              className={`flex w-full items-center gap-3 text-sm text-left transition-colors ${rowClassName} ${
                i === selectedIndex
                  ? "bg-primary/10 text-foreground"
                  : "text-foreground hover:bg-muted"
              }`}
              onMouseEnter={() => onHover?.(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onSelect(r)}
            >
              <SearchResultItem result={r} isTracked={isTracked} symbolClassName={symbolClassName} />
            </button>
          </div>
        )
      })}
    </>
  )
}
