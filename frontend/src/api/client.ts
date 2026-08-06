import type { BulkMutationResult, InboundLinkList, InventoryList, LinkOccurrence, ManualUrlBatchResult, Note, NoteList, OutgoingLinkList, PageCategory, PageCategoryList, PageList, PageObservationList, PersistentPageDetail, PersistentPageList, RenderCapabilities, RenderedConsoleMessage, RenderedEventList, RenderedNetworkEntry, RenderedObservation, RenderedPageError, Scan, ScanDeletePreview, ScanDeleteResult, ScanHistory, ScanSeedList, ScopeConfig, Site, SiteList, SitePayload, SiteScans, Snapshot, SourceRefresh, StaticFetchAttempt, UrlSource, UrlSourceEntryList, UrlSourceList } from "../types/scans";
import type { RenderedObservationIndexList, ResourceDetail, ResourceHistoryList, ResourceInventoryList, ResourceOccurrenceList, ResourceSummary } from "../types/scans";
import type { GraphCapabilities, GraphEdgeOccurrenceList, GraphResponse } from "../types/graph";
import type { Job, JobList, WorkerHealth } from "../types/jobs";
import type { AiDeletePreview, AiDiscoveryCandidate, AiDocumentReference, AiDocumentRefresh, AiDocumentSnapshot, AiDocumentSource, AiDocumentSettings, AiValidation, Paginated } from "../types/aiDocuments";
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
  static_max_attempts: 2,
  static_retry_initial_delay_ms: 500,
  static_retry_max_delay_ms: 5000,
  max_html_response_bytes: 2000000,
  concurrent_requests_per_host: 2,
  delay_between_requests_ms: 0,
  user_agent: "WebsiteScanner/0.1",
  drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
  allow_private_networks: false,
  max_redirects: 10,
  enable_http_revalidation: true,
  enable_parse_reuse: true,
  render_mode: "none",
  render_max_pages: 10,
  render_viewport_width: 1440,
  render_viewport_height: 900,
  render_device_scale_factor: 1,
  render_locale: "en-US",
  render_timezone: "UTC",
  render_color_scheme: "light",
  render_reduced_motion: "reduce",
  render_navigation_timeout_seconds: 30,
  render_load_timeout_seconds: 10,
  render_capture_full_page: true,
  render_max_full_page_height: 20000,
  render_max_dom_bytes: 5000000,
  render_max_screenshot_bytes: 15000000,
  render_max_network_entries: 1000,
  render_max_console_entries: 200,
  render_max_page_errors: 50,
  render_max_page_duration_seconds: 60,
  render_max_total_network_bytes: 50000000,
  render_max_resource_bytes: 10000000
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
export const discoverAiDocumentSources = (siteId: string) => request<{ candidates: AiDiscoveryCandidate[] }>(`/api/sites/${siteId}/ai-document-sources/discover`, { method: "POST" });
export const createAiDocumentSource = (siteId: string, payload: { entry_url: string; name: string; discovery_mode?: string; is_active?: boolean; settings?: AiDocumentSettings }) => request<AiDocumentSource>(`/api/sites/${siteId}/ai-document-sources`, { method: "POST", body: JSON.stringify(payload) });
export const getAiDocumentSource = (sourceId: string) => request<AiDocumentSource>(`/api/ai-document-sources/${sourceId}`);
export const updateAiDocumentSource = (sourceId: string, payload: { entry_url: string; name: string; discovery_mode: string; is_active: boolean; settings: AiDocumentSettings }) => request<AiDocumentSource>(`/api/ai-document-sources/${sourceId}`, { method: "PATCH", body: JSON.stringify(payload) });
export const listAiDocumentRefreshes = (sourceId: string, query = "") => request<Paginated<AiDocumentRefresh>>(`/api/ai-document-sources/${sourceId}/refreshes${query}`);
export const listAiDocuments = (sourceId: string, refreshId: number, query = "") => request<Paginated<AiDocumentSnapshot>>(`/api/ai-document-sources/${sourceId}/refreshes/${refreshId}/documents${query}`);
export const listAiReferences = (sourceId: string, refreshId: number, query = "") => request<Paginated<AiDocumentReference>>(`/api/ai-document-sources/${sourceId}/refreshes/${refreshId}/references${query}`);
export const getAiDocumentTree = (sourceId: string, refreshId: number) => request<{ items: Array<{ snapshot: AiDocumentSnapshot; parent_count: number; cycle: boolean }> }>(`/api/ai-document-sources/${sourceId}/refreshes/${refreshId}/tree`);
export const listAiValidations = (sourceId: string, refreshId: number) => request<AiValidation[]>(`/api/ai-document-sources/${sourceId}/refreshes/${refreshId}/validation`);
export const getAiDocumentSnapshot = (snapshotId: string) => request<AiDocumentSnapshot>(`/api/ai-document-snapshots/${snapshotId}`);
export const getAiDocumentContent = async (snapshotId: string) => { const response = await fetch(`${API_BASE}/api/ai-document-snapshots/${snapshotId}/content`); if (!response.ok) throw errorFromResponse(response.status, await response.text()); return response.text(); };
export const aiDocumentDownloadUrl = (snapshotId: string) => `${API_BASE}/api/ai-document-snapshots/${snapshotId}/download`;
export const getAiSourceDeletePreview = (sourceId: string) => request<AiDeletePreview>(`/api/ai-document-sources/${sourceId}/deletion-preview`);
export const deleteAiDocumentSource = (sourceId: string) => request<{ deleted_source_id: number }>(`/api/ai-document-sources/${sourceId}`, { method: "DELETE" });
export const listSitePages = (siteId: string, query = "") => request<PersistentPageList>(`/api/sites/${siteId}/pages${query}`);
export const getSitePage = (siteId: string, resourceId: string) => request<PersistentPageDetail>(`/api/sites/${siteId}/pages/${resourceId}`);
export const listPageObservations = (siteId: string, resourceId: string, query = "") => request<PageObservationList>(`/api/sites/${siteId}/pages/${resourceId}/observations${query}`);
export const updatePageMetadata = (siteId: string, resourceId: string, payload: { owner_label?: string | null; workflow_status?: string; category_ids?: number[] }) => request<PersistentPageDetail>(`/api/sites/${siteId}/pages/${resourceId}/metadata`, { method: "PATCH", body: JSON.stringify(payload) });
export const listPageCategories = (siteId: string, query = "") => request<PageCategoryList>(`/api/sites/${siteId}/page-categories${query}`);
export const createPageCategory = (siteId: string, payload: { name: string; description?: string | null; color_key: string; sort_order?: number }) => request<PageCategory>(`/api/sites/${siteId}/page-categories`, { method: "POST", body: JSON.stringify(payload) });
export const updatePageCategory = (siteId: string, categoryId: number, payload: Partial<Pick<PageCategory, "name" | "description" | "color_key" | "sort_order" | "is_active">>) => request<PageCategory>(`/api/sites/${siteId}/page-categories/${categoryId}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deletePageCategory = (siteId: string, categoryId: number) => request<{ deleted_category_id: number }>(`/api/sites/${siteId}/page-categories/${categoryId}`, { method: "DELETE" });
export const bulkPageCategories = (siteId: string, payload: { resource_ids: number[]; add_category_ids: number[]; remove_category_ids: number[] }) => request<BulkMutationResult>(`/api/sites/${siteId}/pages/bulk-categories`, { method: "POST", body: JSON.stringify(payload) });
export const bulkPageMetadata = (siteId: string, payload: { resource_ids: number[]; owner_label?: string | null; workflow_status?: string }) => request<BulkMutationResult>(`/api/sites/${siteId}/pages/bulk-metadata`, { method: "POST", body: JSON.stringify(payload) });

export const listSiteNotes = (siteId: string, query = "") => request<NoteList>(`/api/sites/${siteId}/notes${query}`);
export const createSiteNote = (siteId: string, body: string, isPinned = false) => request<Note>(`/api/sites/${siteId}/notes`, { method: "POST", body: JSON.stringify({ body, is_pinned: isPinned }) });
export const listScanNotes = (scanId: string, query = "") => request<NoteList>(`/api/scans/${scanId}/notes${query}`);
export const createScanNote = (scanId: string, body: string, isPinned = false) => request<Note>(`/api/scans/${scanId}/notes`, { method: "POST", body: JSON.stringify({ body, is_pinned: isPinned }) });
export const listPageNotes = (siteId: string, resourceId: string, query = "") => request<NoteList>(`/api/sites/${siteId}/pages/${resourceId}/notes${query}`);
export const createPageNote = (siteId: string, resourceId: string, body: string, isPinned = false) => request<Note>(`/api/sites/${siteId}/pages/${resourceId}/notes`, { method: "POST", body: JSON.stringify({ body, is_pinned: isPinned }) });
export const updateNote = (noteId: number, payload: { body?: string; is_pinned?: boolean }) => request<Note>(`/api/notes/${noteId}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteNote = (noteId: number) => request<{ deleted_note_id: number }>(`/api/notes/${noteId}`, { method: "DELETE" });

export const listScans = () => request<Scan[]>("/api/scans");
export const listScanHistory = (query = "") => request<ScanHistory>(`/api/scans/history${query}`);
export const getScan = (id: string) => request<Scan>(`/api/scans/${id}`);
export const cancelScan = (id: string) => request<Scan>(`/api/scans/${id}/cancel`, { method: "POST" });
export const getScanDeletePreview = (id: string) => request<ScanDeletePreview>(`/api/scans/${id}/delete-preview`);
export const deleteScan = (id: string) => request<ScanDeleteResult>(`/api/scans/${id}`, { method: "DELETE" });
export const listPages = (scanId: string, query = "") => request<PageList>(`/api/scans/${scanId}/pages${query}`);
export const listScanResources = (scanId: string, query = "") => request<ResourceInventoryList>(`/api/scans/${scanId}/resources${query}`);
export const getScanResourceSummary = (scanId: string) => request<ResourceSummary>(`/api/scans/${scanId}/resources/summary`);
export const getScanResource = (scanId: string, resourceId: string) => request<ResourceDetail>(`/api/scans/${scanId}/resources/${resourceId}`);
export const listScanResourceOccurrences = (scanId: string, resourceId: string, query = "") => request<ResourceOccurrenceList>(`/api/scans/${scanId}/resources/${resourceId}/occurrences${query}`);
export const listSiteResources = (siteId: string, query = "") => request<ResourceInventoryList>(`/api/sites/${siteId}/resources${query}`);
export const getSiteResourceSummary = (siteId: string) => request<ResourceSummary>(`/api/sites/${siteId}/resources/summary`);
export const getSiteResource = (siteId: string, resourceId: string) => request<ResourceDetail>(`/api/sites/${siteId}/resources/${resourceId}`);
export const listSiteResourceOccurrences = (siteId: string, resourceId: string, query = "") => request<ResourceOccurrenceList>(`/api/sites/${siteId}/resources/${resourceId}/occurrences${query}`);
export const listSiteResourceHistory = (siteId: string, resourceId: string, query = "") => request<ResourceHistoryList>(`/api/sites/${siteId}/resources/${resourceId}/history${query}`);
export const listScanRenderedObservations = (scanId: string, query = "") => request<RenderedObservationIndexList>(`/api/scans/${scanId}/rendered-observations${query}`);
export const listErrors = (scanId: string) => request<Snapshot[]>(`/api/scans/${scanId}/errors`);
export const getSnapshot = (snapshotId: string) => request<Snapshot>(`/api/snapshots/${snapshotId}`);
export const getStaticFetchAttempts = (snapshotId: string) => request<StaticFetchAttempt[]>(`/api/snapshots/${snapshotId}/static-fetch-attempts`);
export const getLinks = (snapshotId: string) => request<LinkOccurrence[]>(`/api/snapshots/${snapshotId}/links`);
export const getOutgoingLinks = (snapshotId: string, query = "") => request<OutgoingLinkList>(`/api/snapshots/${snapshotId}/outgoing-links${query}`);
export const getInboundLinks = (snapshotId: string, query = "") => request<InboundLinkList>(`/api/snapshots/${snapshotId}/inbound-links${query}`);
export const listScanSeeds = (scanId: string, query = "") => request<ScanSeedList>(`/api/scans/${scanId}/seeds${query}`);
export const getScanGraph = (scanId: string, query = "") => request<GraphResponse>(`/api/scans/${scanId}/graph${query}`);
export const getGraphEdgeOccurrences = (scanId: string, edgeId: string, query = "") => request<GraphEdgeOccurrenceList>(`/api/scans/${scanId}/graph/edges/${edgeId}/occurrences${query}`);
export const getGraphCapabilities = () => request<GraphCapabilities>("/api/graph/capabilities");
export const getRenderCapabilities = () => request<RenderCapabilities>("/api/rendering/capabilities");
export const getRenderedObservation = (snapshotId: string) => request<RenderedObservation>(`/api/snapshots/${snapshotId}/rendered`);
export const getRenderedNetwork = (id: number, query = "") => request<RenderedEventList<RenderedNetworkEntry>>(`/api/rendered-observations/${id}/network${query}`);
export const getRenderedConsole = (id: number, query = "") => request<RenderedEventList<RenderedConsoleMessage>>(`/api/rendered-observations/${id}/console${query}`);
export const getRenderedErrors = (id: number, query = "") => request<RenderedEventList<RenderedPageError>>(`/api/rendered-observations/${id}/errors${query}`);
export const renderedArtifactUrl = (id: number) => `${API_BASE}/api/rendered-artifacts/${id}/content`;
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

