export type ComparisonScan = { id: number; status: string; starting_url: string; created_at: string; started_at: string | null; finished_at: string | null; stop_reason: string | null; failed_count: number };

export type ScanComparisonBuild = {
  id: number; scan_comparison_id: number; comparison_version: string; algorithm_identity: string; status: string;
  baseline_projection_build_id: number | null; target_projection_build_id: number | null;
  baseline_projection_version: string | null; target_projection_version: string | null;
  baseline_projection_algorithm_identity: string | null; target_projection_algorithm_identity: string | null;
  baseline_projection_checksum: string | null; target_projection_checksum: string | null;
  baseline_scope_fingerprint: string | null; target_scope_fingerprint: string | null;
  baseline_seed_fingerprint: string | null; target_seed_fingerprint: string | null;
  coverage_state: string | null; warnings_json: string[]; validation_json: Record<string, unknown>;
  comparison_checksum_sha256: string | null; started_at: string | null; finished_at: string | null;
  failed_at: string | null; build_duration_ms: number | null; error_type: string | null; error_message: string | null;
  page_result_count: number; resource_result_count: number; link_result_count: number; created_at: string;
};

export type ScanComparison = {
  id: number; website_property_id: number; baseline_scan_id: number; target_scan_id: number;
  current_build_id: number | null; created_at: string; updated_at: string;
  baseline_scan: ComparisonScan; target_scan: ComparisonScan;
  current_build: ScanComparisonBuild | null; active_build: ScanComparisonBuild | null;
};

export type ScanComparisonJobProgress = {
  id: number; status: string; current_operation: string | null;
  progress_current: number | null; progress_total: number | null; progress_unit: string | null;
  started_at: string | null; heartbeat_at: string | null;
};

export type ScanComparisonOverview = { comparison: ScanComparison; summary: { pages: Record<string, number>; resources: Record<string, number>; links: Record<string, number>; scan: Record<string, unknown> } | null; active_job?: ScanComparisonJobProgress | null };
export type ScanComparisonList = { items: ScanComparison[]; total: number; limit: number; offset: number };

export type ComparisonPage = {
  id: number; resource_id: number; normalized_url: string; host: string; path: string;
  baseline_page_projection_id: number | null; target_page_projection_id: number | null;
  baseline_snapshot_id: number | null; target_snapshot_id: number | null;
  presence_state: string; baseline_presence_detail: string; target_presence_detail: string;
  change_state: string; content_state: string; head_state: string; changed_field_count: number;
  exact_source_state: string; exact_source_changed: boolean;
  baseline_normalized_source_hash: string | null; target_normalized_source_hash: string | null;
  normalized_source_state: string; document_content_state: string; metadata_state: string; technical_state: string;
  primary_change_class: string; normalization_only_changed: boolean;
  source_difference_categories_json: string[]; normalization_details_json: Array<Record<string, unknown>>;
  content_changed: boolean; head_changed: boolean; http_status_changed: boolean; fetch_state_changed: boolean;
  final_url_changed: boolean; redirect_state_changed: boolean; content_type_changed: boolean; title_changed: boolean;
  canonical_changed: boolean; robots_changed: boolean; language_changed: boolean; depth_changed: boolean;
  inbound_links_changed: boolean; outbound_links_changed: boolean; embedded_resources_changed: boolean;
  baseline_http_status: number | null; target_http_status: number | null;
  baseline_content_hash: string | null; target_content_hash: string | null;
  baseline_head_hash: string | null; target_head_hash: string | null;
  response_time_ms_delta: number | null; network_bytes_delta: number | null;
  raw_html_size_delta: number | null; stored_html_size_delta: number | null;
  outgoing_edges_newly_observed: number; outgoing_edges_not_observed: number; outgoing_edges_changed: number;
  incoming_edges_newly_observed: number; incoming_edges_not_observed: number; incoming_edges_changed: number;
  baseline_json: Record<string, unknown> | null; target_json: Record<string, unknown> | null;
};

export type ComparisonResource = {
  id: number; resource_id: number; normalized_url: string; host: string; path: string;
  baseline_snapshot_id: number | null; target_snapshot_id: number | null; presence_state: string; change_state: string;
  changed_field_count: number; baseline_kind: string | null; target_kind: string | null;
  baseline_mime_type: string | null; target_mime_type: string | null;
  baseline_http_status: number | null; target_http_status: number | null; status_changed: boolean;
  observed_state_changed: boolean; occurrence_delta: number | null; source_page_delta: number | null;
  declared_size_delta: number | null; baseline_json: Record<string, unknown> | null; target_json: Record<string, unknown> | null;
};

export type ComparisonLink = {
  id: number; source_resource_id: number; target_resource_id: number; source_url: string; target_url: string;
  baseline_source_snapshot_id: number | null; target_source_snapshot_id: number | null;
  presence_state: string; change_state: string; changed_field_count: number;
  baseline_occurrence_count: number; target_occurrence_count: number; occurrence_delta: number;
  baseline_json: Record<string, unknown> | null; target_json: Record<string, unknown> | null;
};

export type ComparisonResultList<T> = { items: T[]; total: number; limit: number; offset: number; comparison_build_id: number; comparison_version: string };
export type SourceDiff = { state: string; diff_text: string; mode: "exact" | "meaningful"; input_truncated: boolean; output_truncated: boolean };
export type OccurrenceDiff = { items: Array<{ state: string; fingerprint: string; occurrence: Record<string, unknown>; count: number }>; total: number; limit: number; offset: number; compared_baseline_count: number; compared_target_count: number; truncated: boolean };
export type PageChangeHistory = { items: Array<{ scan_id: number; snapshot_id: number; scan_created_at: string; scan_status: string; observed_at: string | null; http_status: number | null; fetch_state: string; content_hash: string | null; head_hash: string | null; title: string | null; canonical_url: string | null; robots_directives: string | null; change_label: string; changed_flags: string[]; previous_snapshot_id: number | null; previous_scan_id: number | null; intervening_scan_count: number; intervening_unsuccessful_observation_count: number }>; total: number; limit: number; offset: number };
