import { describe, expect, it } from "vitest";

import { finalValidOffset, pageToOffset, pageTokens, paginationState, TABLE_PAGE_SIZES, withPaginationParams } from "../src/utils/pagination";

describe("table pagination", () => {
  it.each([[0, 1], [1, 1], [50, 1], [51, 2], [250, 5]])("derives total pages for %i results", (total, pages) => expect(paginationState(total, 50, 0).totalPages).toBe(pages));
  it("shows a bounded middle window with ellipses", () => expect(pageTokens(84, 19)).toEqual([1, "ellipsis-start", 17, 18, 19, 20, 21, "ellipsis-end", 84]));
  it("avoids duplicate pages near each end", () => { expect(pageTokens(8, 2)).toEqual([1, 2, 3, 4, "ellipsis-end", 8]); expect(pageTokens(8, 7)).toEqual([1, "ellipsis-start", 5, 6, 7, 8]); });
  it("handles one, two, and five pages", () => { expect(pageTokens(1, 1)).toEqual([1]); expect(pageTokens(2, 1)).toEqual([1, 2]); expect(pageTokens(5, 3)).toEqual([1, 2, 3, 4, 5]); });
  it("derives first and last navigation state", () => { expect(paginationState(100, 25, 0)).toMatchObject({ currentPage: 1, canGoPrevious: false, canGoNext: true }); expect(paginationState(100, 25, 75)).toMatchObject({ currentPage: 4, canGoPrevious: true, canGoNext: false }); });
  it("converts pages to bounded offsets", () => { expect(pageToOffset(3, 50, 2332)).toBe(100); expect(pageToOffset(99, 50, 120)).toBe(100); });
  it("moves invalid offsets to the final valid page", () => expect(finalValidOffset(376, 50)).toBe(350));
  it("never reports an impossible result range", () => expect(paginationState(51, 50, 50)).toMatchObject({ firstVisibleItem: 51, lastVisibleItem: 51 }));
  it("offers the standard table sizes", () => expect(TABLE_PAGE_SIZES).toEqual([25, 50, 100, 250]));
  it("preserves tabs, filters, and other table prefixes", () => {
    const current = new URLSearchParams("tab=pages&search=docs&resources_limit=100&resources_offset=200");
    const next = withPaginationParams(current, "pages", 250, 0);
    expect(next.toString()).toContain("tab=pages");
    expect(next.toString()).toContain("search=docs");
    expect(next.get("resources_offset")).toBe("200");
    expect(next.get("pages_limit")).toBe("250");
    expect(next.get("pages_offset")).toBe("0");
  });
});
