import type { LinkOccurrence, PageList, Scan, ScopeConfig, Snapshot } from "../types/scans";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export const defaultScope = (): ScopeConfig => ({
  allowed_host_patterns: [],
  excluded_host_patterns: [],
  included_path_prefixes: ["/"],
  excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
  follow_subdomains: true,
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

export const techSmithScope = (): ScopeConfig => ({
  ...defaultScope(),
  allowed_host_patterns: [
    "techsmith.com",
    "*.techsmith.com",
    "techsmith.de",
    "*.techsmith.de",
    "techsmith.fr",
    "*.techsmith.fr",
    "techsmith.es",
    "*.techsmith.es",
    "techsmith.co.jp",
    "*.techsmith.co.jp",
    "techsmith.pt",
    "*.techsmith.pt"
  ],
  excluded_host_patterns: ["support.*"]
});

export function createScan(startingUrl: string, scopeConfig: ScopeConfig) {
  return request<Scan>("/api/scans", {
    method: "POST",
    body: JSON.stringify({ starting_url: startingUrl, scope_config: scopeConfig })
  });
}

export const listScans = () => request<Scan[]>("/api/scans");
export const getScan = (id: string) => request<Scan>(`/api/scans/${id}`);
export const cancelScan = (id: string) => request<Scan>(`/api/scans/${id}/cancel`, { method: "POST" });
export const listPages = (scanId: string, query = "") => request<PageList>(`/api/scans/${scanId}/pages${query}`);
export const listErrors = (scanId: string) => request<Snapshot[]>(`/api/scans/${scanId}/errors`);
export const getSnapshot = (snapshotId: string) => request<Snapshot>(`/api/snapshots/${snapshotId}`);
export const getLinks = (snapshotId: string) => request<LinkOccurrence[]>(`/api/snapshots/${snapshotId}/links`);

export async function getHtml(snapshotId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/api/snapshots/${snapshotId}/html`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.text();
}

