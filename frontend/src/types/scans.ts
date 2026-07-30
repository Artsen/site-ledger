export type Scan = {
  id: number;
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
};

