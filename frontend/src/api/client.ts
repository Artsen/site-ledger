import type { InboundLinkList, LinkOccurrence, PageList, Scan, ScanDeletePreview, ScanDeleteResult, ScanHistory, ScopeConfig, Site, SiteList, SitePayload, SiteScans, Snapshot } from "../types/scans";
import { errorFromResponse } from "../utils/errors";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init
  });
  if (!response.ok) {
    throw errorFromResponse(response.status, await response.text());
  }
  return response.json() as Promise<T>;
}

export const defaultScope = (): ScopeConfig => ({
  allowed_host_patterns: [],
  excluded_host_patterns: [],
  included_path_prefixes: ["/"],
  excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
  follow_subdomains: false,
  max_pages: 100,
  max_depth: 3,
  respect_robots_txt: false,
  request_timeout_seconds: 10,
  max_html_response_bytes: 2000000,
  concurrent_requests_per_host: 2,
  delay_between_requests_ms: 0,
  user_agent: "ArtsenDesignScanner/0.1",
  drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
  allow_private_networks: false,
  max_redirects: 10
});

export function createScan(startingUrl: string, scopeConfig: ScopeConfig, websitePropertyId?: number | null) {
  return request<Scan>("/api/scans", {
    method: "POST",
    body: JSON.stringify({ starting_url: startingUrl, scope_config: scopeConfig, website_property_id: websitePropertyId ?? null })
  });
}

export function createSiteScan(siteId: string, scopeConfig: ScopeConfig) {
  return request<Scan>(`/api/sites/${siteId}/scans`, {
    method: "POST",
    body: JSON.stringify({ scope_config: scopeConfig })
  });
}

export const listSites = (query = "") => request<SiteList>(`/api/sites${query}`);
export const getSite = (id: string) => request<Site>(`/api/sites/${id}`);
export const createSite = (payload: SitePayload) => request<Site>("/api/sites", { method: "POST", body: JSON.stringify(payload) });
export const updateSite = (id: string, payload: Partial<SitePayload>) => request<Site>(`/api/sites/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteSite = (id: string) => request<{ deleted_site_id: number }>(`/api/sites/${id}`, { method: "DELETE" });
export const listSiteScans = (id: string, query = "") => request<SiteScans>(`/api/sites/${id}/scans${query}`);

export const listScans = () => request<Scan[]>("/api/scans");
export const listScanHistory = (query = "") => request<ScanHistory>(`/api/scans/history${query}`);
export const getScan = (id: string) => request<Scan>(`/api/scans/${id}`);
export const cancelScan = (id: string) => request<Scan>(`/api/scans/${id}/cancel`, { method: "POST" });
export const getScanDeletePreview = (id: string) => request<ScanDeletePreview>(`/api/scans/${id}/delete-preview`);
export const deleteScan = (id: string) => request<ScanDeleteResult>(`/api/scans/${id}`, { method: "DELETE" });
export const listPages = (scanId: string, query = "") => request<PageList>(`/api/scans/${scanId}/pages${query}`);
export const listErrors = (scanId: string) => request<Snapshot[]>(`/api/scans/${scanId}/errors`);
export const getSnapshot = (snapshotId: string) => request<Snapshot>(`/api/snapshots/${snapshotId}`);
export const getLinks = (snapshotId: string) => request<LinkOccurrence[]>(`/api/snapshots/${snapshotId}/links`);
export const getInboundLinks = (snapshotId: string, query = "") => request<InboundLinkList>(`/api/snapshots/${snapshotId}/inbound-links${query}`);

export async function getHtml(snapshotId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/api/snapshots/${snapshotId}/html`);
  if (!response.ok) {
    throw errorFromResponse(response.status, await response.text());
  }
  return response.text();
}

