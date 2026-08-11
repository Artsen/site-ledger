import type { ScanComparisonOverview } from "../types/comparisons";

export const COMPARISON_GC_TIME_MS = 45 * 60 * 1000;

export function comparisonIsBuilding(data: ScanComparisonOverview | undefined) {
  return ["queued", "waiting_for_projections", "building"].includes(
    data?.comparison.active_build?.status ?? "",
  );
}

export function comparisonStatusRefetchInterval(data: ScanComparisonOverview | undefined) {
  return comparisonIsBuilding(data) ? 2000 : false as const;
}

export const immutableComparisonQueryOptions = {
  staleTime: Infinity,
  gcTime: COMPARISON_GC_TIME_MS,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  refetchInterval: false as const,
};
