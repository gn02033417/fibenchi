import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { QuoteFreshness } from "./quote-freshness"

describe("QuoteFreshness", () => {
  it.each([
    ["LIVE", false],
    ["CACHED", true],
    ["DISCONNECTED", true],
  ] as const)("renders %s without presenting stale data as live", (status, showsUpdatedAt) => {
    const html = renderToStaticMarkup(
      <QuoteFreshness quote={{ data_status: status, updated_at: "2026-08-19T09:08:00Z" }} />,
    )

    expect(html).toContain(`data-quote-status="${status}"`)
    expect(html).toContain(status)
    expect(html.includes("Last updated")).toBe(showsUpdatedAt)
  })
})
