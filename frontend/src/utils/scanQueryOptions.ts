import type { ScanProjectionStatus } from "../types/scans";

export const TERMINAL_SCAN_GC_TIME_MS = 45 * 60 * 1000;

export function scanResultQueryOptions(
  scanStatus: string | undefined,
  projection: ScanProjectionStatus | undefined
) {
  const terminal = ["completed", "completed_with_errors", "failed", "cancelled", "interrupted"].includes(scanStatus ?? "");
  const prepared = terminal && projection?.projection_source === "materialized" && projection.current_build != null;
  if (prepared) {
    return {
      staleTime: Infinity,
      gcTime: TERMINAL_SCAN_GC_TIME_MS,
      refetchInterval: false as const,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false
    };
  }
  return {
    staleTime: terminal ? 3000 : 0,
    gcTime: TERMINAL_SCAN_GC_TIME_MS,
    refetchInterval: terminal ? false as const : 2000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true
  };
}

export function projectionStatusRefetchInterval(status: ScanProjectionStatus | undefined) {
  if (!status || status.projection_status === "queued" || status.projection_status === "building" || status.projection_status === "missing") return 2000;
  return false as const;
}
