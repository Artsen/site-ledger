import { describe, expect, it, vi } from "vitest";

import { formatDate, formatRelativeDate } from "../src/utils/format";

describe("Site timezone formatting", () => {
  it("renders one instant in different Site timezones", () => {
    const instant = "2026-08-07T02:23:00Z";
    const eastern = formatDate(instant, { timeZone: "America/New_York", showTimeZone: true, locale: "en-US" });
    const pacific = formatDate(instant, { timeZone: "America/Los_Angeles", showTimeZone: true, locale: "en-US" });
    expect(eastern).toContain("10:23 PM");
    expect(eastern).toContain("EDT");
    expect(pacific).toContain("7:23 PM");
    expect(pacific).toContain("PDT");
  });

  it("uses EST and EDT according to the instant", () => {
    expect(formatDate("2026-01-15T17:00:00Z", { timeZone: "America/New_York", showTimeZone: true, locale: "en-US" })).toContain("EST");
    expect(formatDate("2026-07-15T16:00:00Z", { timeZone: "America/New_York", showTimeZone: true, locale: "en-US" })).toContain("EDT");
  });

  it("treats legacy timezone-less backend timestamps as UTC", () => {
    const withZone = formatDate("2026-08-07T02:23:00Z", { timeZone: "America/New_York", locale: "en-US" });
    const legacy = formatDate("2026-08-07T02:23:00", { timeZone: "America/New_York", locale: "en-US" });
    expect(legacy).toBe(withZone);
  });

  it("keeps relative dates based on elapsed time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-07T02:23:00Z"));
    expect(formatRelativeDate("2026-08-07T01:23:00Z")).toBe("1 hour ago");
    vi.useRealTimers();
  });
});
