import type { SiteIntelligence } from "../types/siteIntelligence";
import { errorFromResponse } from "../utils/errors";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export async function getSiteIntelligence(siteId: string | number): Promise<SiteIntelligence> {
  const response = await fetch(`${API_BASE}/api/sites/${siteId}/intelligence`);
  if (!response.ok) throw errorFromResponse(response.status, await response.text());
  return response.json() as Promise<SiteIntelligence>;
}
