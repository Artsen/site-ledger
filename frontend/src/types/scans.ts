export type Scan = {
  id: number;
  website_property_id: number | null;
  website_property_name: string | null;
  website_property_base_url: string | null;
  website_property_display_timezone?: string | null;
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
  conditional_request_count: number;
  not_modified_count: number;
  parse_reuse_count: number;
  full_parse_count: number;
  network_bytes_transferred: number;
  reused_content_bytes: number;
  rendered_selected_count: number;
  rendered_attempted_count: number;
  rendered_completed_count: number;
  rendered_failed_count: number;
  rendered_skipped_count: number;
  rendered_blocked_request_count: number;
  rendered_artifact_count: number;
  render_run_id?: number | null;
  render_run_status?: string | null;
  static_request_attempt_count: number;
  static_retry_request_count: number;
  static_recovered_after_retry_count: number;
  static_retry_exhausted_count: number;
  static_connection_timeout_count: number;
  static_read_timeout_count: number;
  static_connection_error_count: number;
  html_page_observed_count?: number;
  resource_observed_count?: number;
  resource_discovered_count?: number;
  resource_reference_occurrence_count?: number;
  stop_reason: string | null;
  fatal_error_message: string | null;
};

export type ProjectionMetadata = {
  projection_source: "materialized" | "dynamic";
  projection_version: string;
  projection_build_id: number | null;
  projection_status: string;
};

export type ScanProjectionBuild = {
  id: number;
  scan_id: number;
  projection_version: string;
  algorithm_identity: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  failed_at: string | null;
  error_type: string | null;
  error_message: string | null;
  page_count: number;
  resource_count: number;
  link_edge_count: number;
  graph_node_count: number;
  graph_edge_count: number;
  rendered_page_count: number;
  source_snapshot_count: number;
  source_link_occurrence_count: number;
  source_resource_reference_count: number;
  build_duration_ms: number | null;
  checksum_sha256: string | null;
  validation_json: Record<string, unknown>;
  created_at: string;
};

export type ScanProjectionStatus = {
  scan_id: number;
  scan_status: string;
  expected_version: string;
  projection_source: "materialized" | "dynamic";
  projection_status: string;
  current_build: ScanProjectionBuild | null;
  active_build: ScanProjectionBuild | null;
  latest_build: ScanProjectionBuild | null;
  can_build: boolean;
  can_rebuild: boolean;
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
  display_timezone: string | null;
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
  display_timezone: string | null;
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
  suppression_id: number | null;
  is_suppressed: boolean;
  suppressed_at: string | null;
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
  static_max_attempts: number;
  static_retry_initial_delay_ms: number;
  static_retry_max_delay_ms: number;
  max_html_response_bytes: number;
  concurrent_requests_per_host: number;
  delay_between_requests_ms: number;
  user_agent: string;
  drop_query_parameters: string[];
  allow_private_networks: boolean;
  max_redirects: number;
  enable_http_revalidation: boolean;
  enable_parse_reuse: boolean;
  render_mode: "none" | "starting_page" | "all_eligible";
  render_max_pages: number;
  render_viewport_width: number;
  render_viewport_height: number;
  render_device_scale_factor: number;
  render_locale: string;
  render_timezone: string;
  render_color_scheme: "light" | "dark" | "no-preference";
  render_reduced_motion: "reduce" | "no-preference";
  render_navigation_timeout_seconds: number;
  render_load_timeout_seconds: number;
  render_capture_full_page: boolean;
  render_max_full_page_height: number;
  render_max_dom_bytes: number;
  render_max_screenshot_bytes: number;
  render_max_network_entries: number;
  render_max_console_entries: number;
  render_max_page_errors: number;
  render_max_page_duration_seconds: number;
  render_max_total_network_bytes: number;
  render_max_resource_bytes: number;
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
  retrieval_method: string | null;
  parse_method: string | null;
  retrieval_http_status: number | null;
  reused_from_snapshot_id: number | null;
  network_bytes_transferred: number | null;
  rendered_capture_state: string | null;
};

export type StaticFetchAttempt = {
  id: number;
  snapshot_id: number;
  attempt_number: number;
  started_at: string;
  finished_at: string;
  requested_url: string;
  final_url: string | null;
  retrieval_http_status: number | null;
  response_time_ms: number | null;
  outcome: string;
  error_type: string | null;
  error_message: string | null;
  redirect_chain: Array<Record<string, unknown>>;
  network_bytes_transferred: number;
  retryable: boolean;
  retry_reason: string | null;
  created_at: string;
};

export type RenderCapabilities = {
  defaults: Pick<ScopeConfig, Extract<keyof ScopeConfig, `render_${string}`>>;
  limits: Record<string, { minimum: number; maximum: number }>;
  supported_modes: string[];
  browser_engine: string;
  artifact_types: string[];
  allowed_request_methods: string[];
  service_workers: string;
};

export type RenderedArtifact = { id: number; artifact_type: string; width: number | null; height: number | null; media_type: string; raw_byte_size: number; stored_byte_size: number; sha256: string; metadata_json: Record<string, unknown> };
export type RenderedObservation = {
  id: number; snapshot_id: number | null; render_run_id: number | null; render_run_target_id: number | null; web_resource_id: number | null; capture_state: string; started_at: string | null; finished_at: string | null;
  requested_url: string; final_url: string | null; navigation_http_status: number | null; document_title: string | null;
  browser_engine: string; browser_version: string | null; playwright_version: string | null; renderer_version: string;
  browser_policy_version: string; capture_schema_version: string; user_agent: string | null; viewport_width: number;
  viewport_height: number; device_scale_factor: number; locale: string; timezone_id: string; color_scheme: string;
  reduced_motion: string; readiness_state: string | null; load_event_reached: boolean; fonts_ready_reached: boolean;
  duration_ms: number | null; configuration_fingerprint: string; network_entry_count: number; blocked_request_count: number;
  console_message_count: number; page_error_count: number; warning_count: number; network_truncated: boolean;
  console_truncated: boolean; page_errors_truncated: boolean; total_encoded_network_bytes: number; error_type: string | null;
  error_message: string | null; warnings_json: Array<Record<string, string>>; artifacts: RenderedArtifact[];
};
export type RenderedEventList<T> = { items: T[]; total: number; limit: number; offset: number };
export type RenderedNetworkEntry = { id: number; sequence: number; redacted_url: string; method: string; resource_type: string | null; response_status: number | null; response_mime_type: string | null; encoded_data_length: number | null; blocked_by_policy: boolean; policy_reason: string | null };
export type RenderedConsoleMessage = { id: number; sequence: number; message_type: string; text: string; source_url: string | null; timestamp_offset_ms: number | null };
export type RenderedPageError = { id: number; sequence: number; error_name: string | null; message: string; stack: string | null; source_url: string | null; timestamp_offset_ms: number | null };

export type RenderedObservationIndexItem = {
  id: number;
  snapshot_id: number | null;
  render_run_target_id: number | null;
  resource_id: number;
  page_title: string | null;
  static_final_url: string | null;
  browser_final_url: string | null;
  capture_state: string;
  static_http_status: number | null;
  navigation_http_status: number | null;
  error_type: string | null;
  error_message: string | null;
  duration_ms: number | null;
  warning_count: number;
  blocked_request_count: number;
  console_message_count: number;
  page_error_count: number;
  has_viewport_screenshot: boolean;
  has_full_page_screenshot: boolean;
  has_rendered_dom: boolean;
  finished_at: string | null;
};

export type RenderedObservationIndexList = {
  items: RenderedObservationIndexItem[];
  total: number;
  limit: number;
  offset: number;
  summary: {
    successful_renders: number;
    no_content_responses: number;
    redirect_responses: number;
    http_error_responses: number;
    rate_limited: number;
    skipped_after_throttling: number;
    technical_failures: number;
    artifacts_retained: number;
  };
};

export type RenderRun = {
  id: number;
  website_property_id: number;
  source_scan_id: number | null;
  source_render_run_id: number | null;
  status: string;
  trigger: "scan" | "site_workspace" | "page_workspace" | "rerender";
  configuration_json: ScopeConfig & Record<string, unknown>;
  target_count: number;
  attempted_count: number;
  completed_count: number;
  failed_count: number;
  skipped_count: number;
  blocked_request_count: number;
  artifact_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_summary: string | null;
  job_id: number | null;
  presentation_status: string | null;
  summary: RenderedObservationIndexList["summary"];
};

export type RenderRunList = { items: RenderRun[]; total: number; limit: number; offset: number };
export type RenderRunDetail = RenderRun & { observations: RenderedObservationIndexList };

export type ResourceInventoryItem = {
  resource_id: number;
  normalized_url: string;
  host: string;
  path: string;
  file_extension: string | null;
  effective_kind: string;
  effective_kind_label: string;
  classification_source: string;
  observed: boolean;
  discovered_only: boolean;
  snapshot_id: number | null;
  final_url: string | null;
  http_status: number | null;
  normalized_mime_type: string | null;
  content_disposition_filename: string | null;
  declared_content_length: number | null;
  network_bytes_transferred: number | null;
  fetched_at: string | null;
  response_time_ms: number | null;
  occurrence_count: number;
  source_page_count: number;
  anchor_occurrence_count: number;
  embedded_occurrence_count: number;
  in_scope_occurrence_count: number;
  out_of_scope_occurrence_count: number;
  first_discovered_at: string | null;
  latest_discovered_at: string | null;
  observation_count: number;
  scan_count: number;
};

export type ResourceInventoryList = { items: ResourceInventoryItem[]; total: number; limit: number; offset: number; projection?: ProjectionMetadata | null };
export type ResourceSummary = { unique_resources: number; observed_resources: number; discovered_only_resources: number; total_occurrences: number; kind_counts: Record<string, number>; projection?: ProjectionMetadata | null };
export type ResourceDetail = { resource: ResourceInventoryItem; requested_url: string | null; response_body_state: string | null; inspected_prefix_byte_count: number };
export type ResourceOccurrence = {
  occurrence_id: number;
  occurrence_source: string;
  source_snapshot_id: number;
  source_resource_id: number;
  source_url: string;
  source_title: string | null;
  relation_type: string;
  element_tag: string | null;
  attribute_name: string | null;
  raw_url: string | null;
  resolved_url: string | null;
  anchor_text: string | null;
  alt_text: string | null;
  srcset_descriptor: string | null;
  rel: string | null;
  media: string | null;
  type_hint: string | null;
  as_hint: string | null;
  scope_decision: string;
  in_scope: boolean;
  dom_path: string | null;
  discovered_at: string;
};
export type ResourceOccurrenceList = { items: ResourceOccurrence[]; total: number; limit: number; offset: number };
export type ResourceHistoryItem = { resource_id: number; scan_id: number; scan_created_at: string; scan_status: string; observed: boolean; discovered_only: boolean; effective_kind: string; normalized_mime_type: string | null; http_status: number | null; declared_content_length: number | null; occurrence_count: number; observed_at: string | null; snapshot_id: number | null };
export type ResourceHistoryList = { items: ResourceHistoryItem[]; total: number; limit: number; offset: number };

export type PageList = {
  items: Page[];
  total: number;
  limit: number;
  offset: number;
  projection?: ProjectionMetadata | null;
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
  parse_artifact_id: number | null;
  reused_from_snapshot_id: number | null;
  retrieval_method: string | null;
  parse_method: string | null;
  retrieval_http_status: number | null;
  retrieval_response_headers: Record<string, unknown> | null;
  network_bytes_transferred: number | null;
  request_variant_fingerprint: string | null;
  etag: string | null;
  last_modified: string | null;
  cache_control: string | null;
  vary_header: string | null;
  representation_kind?: string | null;
  representation_rule?: string | null;
  normalized_mime_type?: string | null;
  file_extension?: string | null;
  content_disposition_filename?: string | null;
  declared_content_length?: number | null;
  response_body_state?: string | null;
  inspected_prefix_byte_count?: number;
  website_property_id: number | null;
  website_property_name: string | null;
  site_page_id: number | null;
  has_persistent_page: boolean;
  is_html_page: boolean;
};

export type PersistentPage = {
  site_page_id: number;
  resource_id: number;
  normalized_url: string;
  host: string;
  path: string;
  query: string;
  owner_label: string | null;
  workflow_status: string;
  workspace_state: "active" | "suppressed";
  suppressed_at: string | null;
  categories: PageCategory[];
  category_count: number;
  note_count: number;
  associated_at: string;
  observation_count: number;
  first_observed_at: string | null;
  latest_observed_at: string | null;
  latest_snapshot_id: number | null;
  latest_scan_id: number | null;
  latest_http_status: number | null;
  latest_title: string | null;
  latest_retrieval_method: string | null;
  latest_parse_method: string | null;
  latest_reused_from_snapshot_id: number | null;
  latest_fetch_state: string | null;
  latest_error_type: string | null;
  latest_error_message: string | null;
};

export type PersistentPageList = {
  items: PersistentPage[];
  total: number;
  limit: number;
  offset: number;
};

export type PersistentPageDetail = {
  page: PersistentPage;
  site_id: number;
  site_name: string;
};

export type StructuredContentSection = {
  id: number;
  position: number;
  parent_section_id: number | null;
  kind: "heading" | "preamble" | "unheaded";
  heading_level: number | null;
  heading_text: string | null;
  heading_dom_path: string | null;
  region_key: string;
  region_dom_path: string | null;
  direct_text: string;
  direct_text_sha256: string;
  section_sha256: string;
  subtree_sha256: string;
  direct_word_count: number;
  direct_character_count: number;
  subtree_word_count: number;
  subtree_character_count: number;
  child_count: number;
  descendant_count: number;
  block_count: number;
  has_direct_content: boolean;
};

export type StructuredContent = {
  status: "ready" | "partial" | "unavailable" | "not_prepared" | "not_applicable";
  reason: string | null;
  provenance: {
    snapshot_id: number;
    scan_id: number;
    site_id: number | null;
    content_blob_id: number;
    raw_html_sha256: string | null;
    requested_url: string;
    final_url: string | null;
    fetched_at: string | null;
    retrieval_method: string | null;
    reused_from_snapshot_id: number | null;
  } | null;
  artifact: {
    id: number;
    extractor_version: string;
    extractor_config_version: string;
    extraction_state: string;
    document_profile: string;
    section_count: number;
    heading_count: number;
    heading_counts: Record<string, number>;
    document_word_count: number;
    document_character_count: number;
    document_text_sha256: string;
    outline_sha256: string;
    is_truncated: boolean;
    truncation_reasons: string[];
    created_at: string;
  } | null;
  items: StructuredContentSection[];
  total: number;
  limit: number;
  offset: number;
};

export type PageObservation = {
  snapshot_id: number;
  scan_id: number;
  site_id: number | null;
  site_name: string | null;
  scan_created_at: string;
  scan_status: string;
  scan_started_at: string | null;
  scan_finished_at: string | null;
  observed_at: string | null;
  requested_url: string;
  final_url: string | null;
  http_status: number | null;
  retrieval_http_status: number | null;
  fetch_state: string;
  error_type: string | null;
  crawl_depth: number;
  response_time_ms: number | null;
  content_type: string | null;
  raw_html_sha256: string | null;
  head_sha256: string | null;
  page_title: string | null;
  canonical_url: string | null;
  retrieval_method: string | null;
  parse_method: string | null;
  content_blob_id: number | null;
  parse_artifact_id: number | null;
  reused_from_snapshot_id: number | null;
  network_bytes_transferred: number | null;
  parser_version: string | null;
  rendered_capture_state: string | null;
};

export type PageObservationList = {
  items: PageObservation[];
  total: number;
  limit: number;
  offset: number;
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
  link_role: string | null;
  link_role_label: string;
  link_role_rule: string | null;
  link_context_json: Record<string, unknown> | null;
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
    role_counts: Record<string, number>;
  };
};

export type OutgoingLinkList = {
  items: LinkOccurrence[];
  total: number;
  limit: number;
  offset: number;
  summary: {
    total_occurrences: number;
    nofollow_occurrences: number;
    in_scope_occurrences: number;
    role_counts: Record<string, number>;
  };
};

export type PageCategory = {
  id: number;
  website_property_id: number;
  name: string;
  description: string | null;
  color_key: string;
  sort_order: number;
  is_active: boolean;
  assignment_count: number;
  manual_assignment_count: number;
  automatic_assignment_count: number;
  exclusion_count: number;
  rule_count: number;
  created_at: string;
  updated_at: string;
};

export type CategoryRuleCondition = {
  id?: number;
  rule_id?: number;
  target: "normalized_url" | "host" | "path" | "query" | "filename";
  operator: "equals" | "starts_with" | "ends_with" | "contains" | "glob" | "regex";
  value: string;
  negate: boolean;
  case_sensitive: boolean;
  sort_order: number;
  created_at?: string;
};

export type CategoryRule = {
  id: number;
  website_property_id: number;
  category_id: number;
  category_name: string;
  name: string;
  description: string | null;
  match_mode: "all" | "any";
  is_active: boolean;
  sort_order: number;
  current_revision_number: number;
  current_match_count: number;
  current_excluded_count: number;
  last_evaluated_at: string | null;
  created_at: string;
  updated_at: string;
  conditions: CategoryRuleCondition[];
};

export type CategoryRuleList = { items: CategoryRule[]; total: number; limit: number; offset: number };
export type CategoryRulePreview = {
  total_pages_evaluated: number;
  matching_pages: number;
  currently_assigned: number;
  would_gain_automatic_support: number;
  would_lose_automatic_support: number;
  excluded_matches: number;
  sample_matching_pages: Array<{ resource_id: number; normalized_url: string }>;
  sample_non_matching_pages: Array<{ resource_id: number; normalized_url: string }>;
  invalid_conditions: string[];
  evaluation_duration_ms: number;
};
export type CategoryRuleRun = {
  id: number;
  website_property_id: number;
  trigger_type: string;
  trigger_rule_id: number | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  page_count: number;
  rule_count: number;
  condition_count: number;
  match_count: number;
  rule_supports_added: number;
  rule_supports_removed: number;
  effective_assignments_added: number;
  effective_assignments_removed: number;
  exclusions_suppressing_matches: number;
  unchanged_count: number;
  error_type: string | null;
  error_message: string | null;
  evaluator_version: string;
  created_at: string;
};
export type CategoryRuleRunList = { items: CategoryRuleRun[]; total: number; limit: number; offset: number };
export type CategoryProvenance = {
  category_id: number;
  category_name: string;
  manually_assigned: boolean;
  matching_rules: Array<{ id: number; name: string }>;
  automatic_exclusion: boolean;
  effective: boolean;
  effective_reason: string;
};

export type PageCategoryList = {
  items: PageCategory[];
  total: number;
  limit: number;
  offset: number;
};

export type PageCategoryDeletionPreview = {
  category: PageCategory;
  assignment_count: number;
  manual_support_count: number;
  rule_support_count: number;
  rule_count: number;
  exclusion_count: number;
  sample_pages: Array<{ resource_id: number; normalized_url: string }>;
  can_delete: boolean;
};

export type Note = {
  id: number;
  website_property_id: number | null;
  scan_id: number | null;
  site_page_id: number | null;
  body: string;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
};

export type NoteList = {
  items: Note[];
  total: number;
  limit: number;
  offset: number;
};

export type BulkMutationResult = {
  selected: number;
  changed: number;
  unchanged: number;
  rejected: number;
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
  rendered_observations?: number;
  rendered_artifacts?: number;
  artifact_blobs_referenced?: number;
  exclusive_artifact_blobs?: number;
  shared_artifact_blobs?: number;
  raw_artifact_bytes_reclaimable?: number;
  stored_artifact_bytes_reclaimable?: number;
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
  rendered_observations_deleted?: number;
  rendered_artifacts_deleted?: number;
  artifact_blob_records_deleted?: number;
  artifact_blob_files_deleted?: number;
  raw_artifact_bytes_reclaimed?: number;
  stored_artifact_bytes_reclaimed?: number;
  warnings: string[];
};

