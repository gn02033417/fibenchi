import { describe, expect, it } from "vitest"
import { buildQuoteStreamUrl } from "./quote-stream-url"

describe("buildQuoteStreamUrl", () => {
  it("keeps the existing intraday demand and adds deterministic active-view demand", () => {
    expect(buildQuoteStreamUrl({
      intradaySymbols: ["2330", "0050", "2330"],
      activeAssets: ["2317", "0050"],
      activeGroupIds: [7, 2, 7],
    })).toBe("/api/quotes/stream?intraday=0050%2C2330&active_asset=0050%2C2317&active_group=2%2C7")
  })

  it("uses the existing base URL when no view declares demand", () => {
    expect(buildQuoteStreamUrl()).toBe("/api/quotes/stream")
  })
})
