import type { InboundLinkList, InventoryList, LinkOccurrence, ManualUrlBatchResult, PageList, Scan, ScanDeletePreview, ScanDeleteResult, ScanHistory, ScanSeedList, ScopeConfig, Site, SiteList, SitePayload, SiteScans, Snapshot, SourceRefresh, UrlSource, UrlSourceEntryList, UrlSourceList } from "../types/scans";
import type { GraphEdgeOccurrenceList, GraphResponse } from "../types/graph";
import type { Job, JobList, WorkerHealth } from "../types/jobs";
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
  user_agent: "WebsiteScanner/0.1",
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

export function createSiteScan(siteId: string, scopeConfig: ScopeConfig, includeInventory = false, sourceIds: number[] = []) {
  return request<Scan>(`/api/sites/${siteId}/scans`, {
    method: "POST",
    body: JSON.stringify({ scope_config: scopeConfig, include_inventory: includeInventory, source_ids: sourceIds })
  });
}

export const listSites = (query = "") => request<SiteList>(`/api/sites${query}`);
export const getSite = (id: string) => request<Site>(`/api/sites/${id}`);
export const createSite = (payload: SitePayload) => request<Site>("/api/sites", { method: "POST", body: JSON.stringify(payload) });
export const updateSite = (id: string, payload: Partial<SitePayload>) => request<Site>(`/api/sites/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteSite = (id: string) => request<{ deleted_site_id: number }>(`/api/sites/${id}`, { method: "DELETE" });
export const listSiteScans = (id: string, query = "") => request<SiteScans>(`/api/sites/${id}/scans${query}`);
export const listSources = (siteId: string, query = "") => request<UrlSourceList>(`/api/sites/${siteId}/sources${query}`);
export const createSource = (siteId: string, payload: Partial<UrlSource>) => request<UrlSource>(`/api/sites/${siteId}/sources`, { method: "POST", body: JSON.stringify(payload) });
export const deleteSource = (siteId: string, sourceId: string) => request<{ deleted_source_id: number }>(`/api/sites/${siteId}/sources/${sourceId}`, { method: "DELETE" });
export const refreshSource = (siteId: string, sourceId: string) => request<SourceRefresh>(`/api/sites/${siteId}/sources/${sourceId}/refresh`, { method: "POST" });
export const discoverRobots = (siteId: string) => request<SourceRefresh>(`/api/sites/${siteId}/sources/discover-robots`, { method: "POST" });
export const cancelSourceRefresh = (refreshId: string) => request<SourceRefresh>(`/api/source-refreshes/${refreshId}/cancel`, { method: "POST" });
export const listSourceEntries = (siteId: string, sourceId: string, query = "") => request<UrlSourceEntryList>(`/api/sites/${siteId}/sources/${sourceId}/entries${query}`);
export const addManualUrls = (siteId: string, urlsText: string) => request<ManualUrlBatchResult>(`/api/sites/${siteId}/manual-urls`, { method: "POST", body: JSON.stringify({ urls_text: urlsText }) });
export const listInventory = (siteId: string, query = "") => request<InventoryList>(`/api/sites/${siteId}/inventory${query}`);

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
export const listScanSeeds = (scanId: string, query = "") => request<ScanSeedList>(`/api/scans/${scanId}/seeds${query}`);
export const getScanGraph = (scanId: string, query = "") => request<GraphResponse>(`/api/scans/${scanId}/graph${query}`);
export const getGraphEdgeOccurrences = (scanId: string, edgeId: string, query = "") => request<GraphEdgeOccurrenceList>(`/api/scans/${scanId}/graph/edges/${edgeId}/occurrences${query}`);
export const listJobs = (query = "") => request<JobList>(`/api/jobs${query}`);
export const getJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}`);
export const getWorkerHealth = () => request<WorkerHealth>("/api/jobs/worker-health");

export async function getHtml(snapshotId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/api/snapshots/${snapshotId}/html`);
  if (!response.ok) {
    throw errorFromResponse(response.status, await response.text());
  }
  return response.text();
}

