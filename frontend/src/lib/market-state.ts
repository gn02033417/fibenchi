// Single source of truth for market-state presentation. Previously the dot
// colour+label map (market-status-dot) and the live-day-view label map lived
// separately and had drifted ("Market open" vs "Regular", "After-hours" vs
// "Post-Market"). Both now consume this.

// Presentation traits for a market state. Deliberately NOT the same thing
// as the backend's MarketStateInfo (app/domain/market_state.py): that one
// carries data traits (active, session_forming); this one carries display
// traits. They share only the six-state vocabulary and the `phase` join key.
export interface MarketStateDisplay {
  /** Tailwind background class for a status dot. */
  dotColor: string
  /** Human-readable label. */
  label: string
  /**
   * Scheduled-phase equivalent — same vocabulary as the backend venue
   * calendar's phase(). "closed" means prices are settled. PREPRE is the
   * overnight state (POST→POSTPOST→PREPRE→PRE): for European venues it lasts
   * the whole night, so it must not masquerade as pre-market. POSTPOST is
   * "after-hours has *ended*" ("POSTMARKET" is not an emitted state).
   */
  phase: "premarket" | "open" | "aftermarket" | "closed"
}

const MARKET_STATES = {
  PRE: { dotColor: "bg-blue-500", label: "Pre-market", phase: "premarket" },
  PREPRE: { dotColor: "bg-zinc-500", label: "Overnight", phase: "closed" },
  REGULAR: { dotColor: "bg-emerald-500", label: "Market open", phase: "open" },
  POST: { dotColor: "bg-orange-500", label: "After-hours", phase: "aftermarket" },
  POSTPOST: { dotColor: "bg-red-500", label: "Closed", phase: "closed" },
  CLOSED: { dotColor: "bg-red-500", label: "Closed", phase: "closed" },
} as const satisfies Record<string, MarketStateDisplay>

/**
 * The market-state vocabulary the backend emits (hand-mirrored from
 * `backend/app/schemas/quote.py` — no codegen). Comparing a MarketState
 * against a string outside this union is a compile error, which is the point:
 * a `=== "POSTMARKET"` typo can no longer type-check.
 */
export type MarketState = keyof typeof MARKET_STATES

const DEFAULT_STATE: MarketStateDisplay = { dotColor: "bg-red-500", label: "Closed", phase: "closed" }

/** Resolve a market-state code to its dot colour + label (falls back to Closed). */
export function marketState(state: MarketState | null | undefined): MarketStateDisplay {
  // Runtime guard stays: the API cast is unchecked, so a novel upstream state
  // must still degrade to Closed instead of exploding.
  return (state && MARKET_STATES[state]) || DEFAULT_STATE
}
