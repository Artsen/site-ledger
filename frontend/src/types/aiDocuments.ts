export type AiDocumentSettings = {
  max_nesting_depth: number;
  max_index_documents: number;
  max_total_documents: number;
  max_references_per_document: number;
  max_individual_document_bytes: number;
  max_total_retained_bytes: number;
  max_total_network_bytes: number;
  follow_external_documents: boolean;
  save_declared_documents: boolean;
  request_timeout_seconds: number;
  max_attempts: number;
};

export type AiDiscoveryCandidate = {
  url: string;
  discovery_method: string;
  relation: string | null;
  status: "found" | "not_found" | "blocked" | "error";
  http_status: number | null;
  message: string | null;
  already_configured: boolean;
};

export type AiDocumentSource = {
  id: number;
  website_property_id: number;
  site_name: string;
  name: string;
  entry_url: string;
  discovery_mode: string;
  is_active: boolean;
  settings: AiDocumentSettings;
  last_refresh_status: string | null;
  last_successful_refresh_at: string | null;
  current_entry_count: number;
  latest_refresh_id: number | null;
  latest_source_refresh_id: number | null;
  document_count: number;
  reference_count: number;
  warning_count: number;
  retained_bytes: number;
};

export type AiDocumentRefresh = {
  id: number;
  source_refresh_id: number;
  status: string;
  configuration_json: AiDocumentSettings;
  root_candidate_count: number;
  document_discovered_count: number;
  document_fetched_count: number;
  document_saved_count: number;
  document_unchanged_count: number;
  document_changed_count: number;
  document_failed_count: number;
  document_skipped_count: number;
  reference_count: number;
  cycle_count: number;
  total_network_bytes: number;
  total_retained_bytes: number;
  stop_reason: string | null;
  fatal_error_message: string | null;
  created_at: string;
};

export type AiDocumentSnapshot = {
  id: number;
  source_id: number | null;
  refresh_id: number;
  resource_id: number;
  requested_url: string;
  final_url: string | null;
  parent_depth_min: number;
  document_role: string;
  document_kind: string;
  classification_rule: string;
  fetch_state: string;
  http_status: number | null;
  normalized_mime_type: string | null;
  encoding: string | null;
  response_headers: Record<string, string>;
  redirect_chain: Array<Record<string, unknown>>;
  fetched_at: string | null;
  response_time_ms: number | null;
  network_bytes_transferred: number;
  raw_sha256: string | null;
  parsed_title: string | null;
  parsed_summary: string | null;
  parse_state: string;
  parse_version: string | null;
  parse_warnings_json: Array<Record<string, unknown>>;
  warning_count: number;
  change_state: string;
  error_type: string | null;
  error_message: string | null;
  raw_byte_size: number | null;
  stored_byte_size: number | null;
  parent_count: number;
};

export type AiDocumentReference = {
  id: number;
  parent_snapshot_id: number;
  target_resource_id: number | null;
  child_snapshot_id: number | null;
  position: number;
  section_title: string | null;
  label: string | null;
  description: string | null;
  raw_url: string;
  resolved_url: string | null;
  normalized_target_url: string | null;
  optional: boolean;
  inferred_role: string;
  inferred_kind: string;
  classification_rule: string;
  in_scope: boolean;
  scope_decision: string;
  exclusion_reason: string | null;
  discovery_depth: number;
  forms_cycle: boolean;
  inventory_entry_id: number | null;
};

export type AiValidation = {
  id: number;
  snapshot_id: number | null;
  reference_id: number | null;
  severity: string;
  code: string;
  message: string;
  data_json: Record<string, unknown>;
};

export type Paginated<T> = { items: T[]; total: number; limit: number; offset: number };

export type AiDeletePreview = {
  refresh_count: number;
  snapshot_count: number;
  reference_count: number;
  current_inventory_origin_count: number;
  unique_blob_count: number;
  shared_blob_count: number;
  exclusive_blob_count: number;
  reclaimable_storage_bytes: number;
};

export const defaultAiDocumentSettings = (): AiDocumentSettings => ({
  max_nesting_depth: 5,
  max_index_documents: 100,
  max_total_documents: 1000,
  max_references_per_document: 10000,
  max_individual_document_bytes: 5000000,
  max_total_retained_bytes: 100000000,
  max_total_network_bytes: 250000000,
  follow_external_documents: false,
  save_declared_documents: true,
  request_timeout_seconds: 10,
  max_attempts: 2,
});
