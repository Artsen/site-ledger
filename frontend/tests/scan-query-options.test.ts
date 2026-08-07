import { describe, expect, it } from "vitest";

import { projectionStatusRefetchInterval, scanResultQueryOptions, TERMINAL_SCAN_GC_TIME_MS } from "../src/utils/scanQueryOptions";
import type { ScanProjectionBuild, ScanProjectionStatus } from "../src/types/scans";

const ready: ScanProjectionStatus = {
  scan_id: 1,
  scan_status: "completed",
  expected_version: "scan-projection-v1",
  projection_source: "materialized",
  projection_status: "ready",
  current_build: { id: 9 } as ScanProjectionBuild,
  active_build: null,
  latest_build: null,
  can_build: false,
  can_rebuild: true
};

describe("Scan result query options", () => {
  it("treats prepared terminal results as immutable during navigation", () => {
    expect(scanResultQueryOptions("completed", ready)).toEqual({
      staleTime: Infinity,
      gcTime: TERMINAL_SCAN_GC_TIME_MS,
      refetchInterval: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false
    });
    expect(TERMINAL_SCAN_GC_TIME_MS).toBeGreaterThanOrEqual(30 * 60 * 1000);
    expect(TERMINAL_SCAN_GC_TIME_MS).toBeLessThanOrEqual(60 * 60 * 1000);
  });

  it("keeps active Scan refresh behavior", () => {
    const options = scanResultQueryOptions("running", undefined);
    expect(options.refetchInterval).toBe(2000);
    expect(options.refetchOnWindowFocus).toBe(true);
    expect(options.refetchOnReconnect).toBe(true);
  });

  it("polls projection state during fallback and stops when ready or failed", () => {
    expect(projectionStatusRefetchInterval(undefined)).toBe(2000);
    expect(projectionStatusRefetchInterval({ ...ready, projection_source: "dynamic", projection_status: "building" })).toBe(2000);
    expect(projectionStatusRefetchInterval(ready)).toBe(false);
    expect(projectionStatusRefetchInterval({ ...ready, projection_source: "dynamic", projection_status: "failed" })).toBe(false);
  });
});
