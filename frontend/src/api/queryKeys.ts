import type { QueryClient } from "@tanstack/react-query";

import type { SiteIntelligence } from "../types/siteIntelligence";

export const SITE_INTELLIGENCE_ACTIVE_REFRESH_MS = 2_000;
export const SITE_INTELLIGENCE_IDLE_REFRESH_MS = 30_000;

export function siteIntelligenceQueryKey(siteId: string | number) {
  return ["site-intelligence", String(siteId)] as const;
}

export function invalidateSiteIntelligence(
  queryClient: QueryClient,
  siteId: string | number,
) {
  return queryClient.invalidateQueries({ queryKey: siteIntelligenceQueryKey(siteId) });
}

export function siteIntelligenceRefetchInterval(data: SiteIntelligence | undefined) {
  return data?.activity.active_job_count
    ? SITE_INTELLIGENCE_ACTIVE_REFRESH_MS
    : SITE_INTELLIGENCE_IDLE_REFRESH_MS;
}
