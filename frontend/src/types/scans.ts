export type Scan = {
  id: number;
  website_property_id: number | null;
  website_property_name: string | null;
  website_property_base_url: string | null;
  starting_url: string;
  status: string;
  scope_config: ScopeConfig;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  discovered_count: number;
  fetched_count: number;
  failed_count: number;
  skipped_count: number;
  queued_count: number;
  stop_reason: string | null;
  fatal_error_message: string | null;
};

export type Site = {
  id: number;
  name: string;
  base_url: string;
  normalized_base_url: string;
  description: string | null;
  group_key: string;
  locale: string | null;
  platform_key: string;
  ownership_key: string;
  scope_config: ScopeConfig;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  total_scan_count: number;
  latest_scan: Scan | null;
  recent_scans: Scan[];
};

export type SiteListItem = Omit<Site, "scope_config" | "total_scan_count" | "latest_scan" | "recent_scans"> & {
  scope_config: ScopeConfig;
  total_scan_count: number;
  latest_scan_id: number | null;
  latest_scan_status: string | null;
  latest_scan_date: string | null;
  latest_scan_discovered_count: number | null;
  latest_scan_failed_count: number | null;
};

export type SiteList = {
  items: SiteListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type SiteScans = {
  items: Scan[];
  total: number;
  limit: number;
  offset: number;
};

export type SitePayload = {
  name: string;
  base_url: string;
  description: string | null;
  group_key: string;
  locale: string | null;
  platform_key: string;
  ownership_key: string;
  scope_config: ScopeConfig;
  is_active: boolean;
};

export type UrlSource = {
  id: number;
  website_property_id: number;
  parent_source_id: number | null;
  root_source_id: number | null;
  source_type: string;
  name: string;
  source_url: string | null;
  normalized_source_url: string | null;
  is_active: boolean;
  discovery_mode: string;
  settings_json: Record<string, unknown>;
  last_refresh_status: string | null;
  last_refresh_started_at: string | null;
  last_refresh_finished_at: string | null;
  last_successful_refresh_at: string | null;
  last_http_status: number | null;
  last_error_type: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
  current_entry_count: number;
};

export type UrlSourceList = {
  items: UrlSource[];
  total: number;
  limit: number;
  offset: number;
};

export type SourceRefresh = {
  id: number;
  url_source_id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  http_status: number | null;
  fetched_url: string | null;
  final_url: string | null;
  response_bytes: number;
  content_type: string | null;
  discovered_entry_count: number;
  accepted_entry_count: number;
  rejected_entry_count: number;
  child_source_count: number;
  entries_added: number;
  entries_updated: number;
  entries_no_longer_current: number;
  error_type: string | null;
  error_message: string | null;
  warnings_json: Array<Record<string, unknown>>;
};

export type UrlSourceEntry = {
  id: number;
  url_source_id: number;
  resource_id: number | null;
  normalized_url: string | null;
  raw_url: string;
  first_seen_at: string;
  last_seen_at: string;
  last_refresh_id: number | null;
  is_current: boolean;
  sitemap_lastmod: string | null;
  sitemap_changefreq: string | null;
  sitemap_priority: string | null;
  source_metadata_json: Record<string, unknown>;
  validation_state: string;
  validation_message: string | null;
  scope_decision: string;
  created_at: string;
  updated_at: string;
};

export type UrlSourceEntryList = {
  items: UrlSourceEntry[];
  total: number;
  limit: number;
  offset: number;
};

export type ManualUrlBatchResult = {
  source: UrlSource;
  items: UrlSourceEntry[];
  accepted_count: number;
  rejected_count: number;
  duplicate_count: number;
};

export type InventoryItem = {
  normalized_url: string | null;
  resource_id: number | null;
  source_count: number;
  source_types: string[];
  sources: Array<Record<string, unknown>>;
  scope_decision: string;
  validation_state: string;
  sitemap_lastmod: string | null;
  latest_scan_status: string | null;
  latest_fetch_date: string | null;
  classification: string;
};

export type InventoryList = {
  items: InventoryItem[];
  total: number;
  limit: number;
  offset: number;
};

export type ScanSeed = {
  id: number;
  scan_id: number;
  resource_id: number | null;
  normalized_url: string | null;
  requested_url: string;
  depth: number;
  queue_state: string;
  scope_decision: string;
  exclusion_reason: string | null;
  created_at: string;
  origins: Array<{
    id: number;
    origin_type: string;
    url_source_id: number | null;
    url_source_entry_id: number | null;
    source_refresh_id: number | null;
    raw_url: string | null;
    metadata_json: Record<string, unknown>;
  }>;
};

export type ScanSeedList = {
  items: ScanSeed[];
  total: number;
  limit: number;
  offset: number;
};

export type ScopeConfig = {
  allowed_host_patterns: string[];
  excluded_host_patterns: string[];
  included_path_prefixes: string[];
  excluded_path_prefixes: string[];
  follow_subdomains: boolean;
  max_pages: number;
  max_depth: number;
  respect_robots_txt: boolean;
  request_timeout_seconds: number;
  max_html_response_bytes: number;
  concurrent_requests_per_host: number;
  delay_between_requests_ms: number;
  user_agent: string;
  drop_query_parameters: string[];
  allow_private_networks: boolean;
  max_redirects: number;
};

export type Page = {
  id: number;
  resource_id: number;
  requested_url: string;
  final_url: string | null;
  http_status: number | null;
  title: string | null;
  depth: number;
  content_type: string | null;
  discovery_source: string | null;
  inbound_occurrence_count: number;
  inbound_source_page_count: number;
  response_time_ms: number | null;
  fetch_state: string;
  error_type: string | null;
};

export type PageList = {
  items: Page[];
  total: number;
  limit: number;
  offset: number;
};

export type Snapshot = {
  id: number;
  scan_id: number;
  resource_id: number;
  requested_url: string;
  final_url: string | null;
  http_status: number | null;
  content_type: string | null;
  encoding: string | null;
  crawl_depth: number;
  fetched_at: string | null;
  response_time_ms: number | null;
  response_headers: Record<string, unknown> | null;
  redirect_chain: Array<Record<string, unknown>> | null;
  html_raw_byte_size: number | null;
  html_stored_byte_size: number | null;
  raw_html_sha256: string | null;
  head_sha256: string | null;
  page_title: string | null;
  html_language: string | null;
  meta_description: string | null;
  meta_robots: string | null;
  canonical_url: string | null;
  parsed_head_json: Record<string, unknown> | null;
  fetch_state: string;
  error_type: string | null;
  error_message: string | null;
};

export type LinkOccurrence = {
  id: number;
  raw_href: string | null;
  resolved_url: string | null;
  normalized_target_url: string | null;
  target_resource_id: number | null;
  anchor_text: string | null;
  title: string | null;
  aria_label: string | null;
  rel: string | null;
  target: string | null;
  dom_path: string | null;
  in_scope: boolean;
  scope_decision: string;
  exclusion_reason: string | null;
  discovered_at: string;
};

export type InboundLinkOccurrence = LinkOccurrence & {
  source_snapshot_id: number;
  source_resource_id: number;
  source_requested_url: string;
  source_final_url: string | null;
  source_page_title: string | null;
  source_http_status: number | null;
  source_fetch_state: string;
  source_crawl_depth: number;
  is_self_link: boolean;
};

export type InboundLinkList = {
  items: InboundLinkOccurrence[];
  total: number;
  limit: number;
  offset: number;
  summary: {
    total_occurrences: number;
    unique_source_pages: number;
    unique_anchor_texts: number;
    nofollow_occurrences: number;
    self_link_occurrences: number;
  };
};

export type ScanHistory = {
  items: Scan[];
  total: number;
  limit: number;
  offset: number;
};

export type ScanDeletePreview = {
  scan_id: number;
  starting_url: string;
  can_delete: boolean;
  status: string;
  snapshots: number;
  link_occurrences: number;
  unique_resources: number;
  html_blobs_referenced: number;
  exclusive_html_blobs: number;
  shared_html_blobs: number;
  html_blobs_deleted: number;
  raw_html_bytes_reclaimable: number;
  stored_html_bytes_reclaimable: number;
  reason: string | null;
  warnings: string[];
};

export type ScanDeleteResult = {
  deleted_scan_id: number;
  snapshots_deleted: number;
  link_occurrences_deleted: number;
  resources_deleted: number;
  html_blob_records_deleted: number;
  html_blob_files_deleted: number;
  html_blobs_deleted: number;
  raw_html_bytes_reclaimed: number;
  stored_html_bytes_reclaimed: number;
  warnings: string[];
};

