export type PerformanceMetric = {
  value: number;
  unit: string;
  histogram?: Array<Record<string, number>>;
};

export type PerformanceProviderCapabilities = {
  pagespeed: { configured: boolean; adapter_version: string };
  crux: { configured: boolean; adapter_version: string };
  normalization_version: string;
  default_page_limit: number;
  hard_page_limit: number;
  absolute_page_limit: number;
  max_provider_requests: number;
  crux_queries_per_minute: number;
};

export type PerformanceRun = {
  id: number;
  website_property_id: number;
  status: string;
  presentation_status: string | null;
  trigger: string;
  configuration_json: {
    resource_ids: number[];
    providers: string[];
    pagespeed_strategies: string[];
    crux_form_factors: string[];
    include_origin_crux: boolean;
  };
  target_count: number;
  request_count: number;
  completed_count: number;
  ready_count: number;
  unavailable_count: number;
  failed_count: number;
  retained_observation_count: number;
  deleted_observation_count: number;
  retained_ready_count: number;
  retained_unavailable_count: number;
  retained_failed_count: number;
  deleted_ready_count: number;
  deleted_unavailable_count: number;
  deleted_failed_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_summary: string | null;
  job_id: number | null;
};

export type PerformanceObservationDeletePreview = {
  can_delete: boolean; reason: string | null; observation_id: number; run_id: number;
  provider: string; dimension: string; outcome: string; observed_at: string;
  target_kind: string; requested_target: string; payload_present: boolean;
  payload_shared: boolean; payload_reference_count: number; payload_raw_bytes: number;
  payload_stored_bytes: number; raw_bytes_reclaimable: number; stored_bytes_reclaimable: number;
};

export type PerformanceRunDeletePreview = {
  can_delete: boolean; reason: string | null; run_id: number; status: string;
  created_at: string; finished_at: string | null; completed_count: number; ready_count: number;
  unavailable_count: number; failed_count: number; retained_observation_count: number;
  deleted_observation_count: number; payload_blobs_referenced: number; exclusive_payload_blobs: number;
  shared_payload_blobs: number; raw_bytes_reclaimable: number; stored_bytes_reclaimable: number;
  background_jobs_removed: number; job_events_removed: number;
};

export type PerformanceSiteDeletePreview = {
  can_delete: boolean; reason: string | null; site_id: number; runs: number;
  retained_observations: number; already_deleted_observations: number;
  background_jobs_removed: number; job_events_removed: number; payload_blobs_referenced: number;
  exclusive_payload_blobs: number; shared_payload_blobs: number; raw_bytes_reclaimable: number;
  stored_bytes_reclaimable: number;
};

export type PerformanceDeleteResult = {
  deleted_observation_id: number | null; deleted_run_id: number | null; purged_site_id: number | null;
  runs_deleted: number; observations_deleted: number; background_jobs_deleted: number;
  job_events_deleted: number; payload_blob_records_deleted: number; payload_blob_files_deleted: number;
  raw_bytes_reclaimed: number; stored_bytes_reclaimed: number; warnings: string[];
};

export type PerformanceObservation = {
  id: number;
  performance_run_id: number;
  website_property_id: number;
  web_resource_id: number | null;
  provider: "pagespeed" | "crux";
  provider_adapter_version: string;
  normalization_version: string;
  target_kind: "url" | "origin";
  requested_target: string;
  provider_target: string | null;
  dimension: string;
  outcome: "ready" | "unavailable" | "failed";
  metrics_json: Record<string, PerformanceMetric>;
  normalized_sha256: string | null;
  provider_analysis_at: string | null;
  provider_period_json: Record<string, unknown> | null;
  provider_product_version: string | null;
  observed_at: string;
  error_type: string | null;
  error_message: string | null;
  page_url: string | null;
  payload_sha256: string | null;
  payload_raw_byte_size: number | null;
  payload_stored_byte_size: number | null;
};

export type PerformanceObservationList = {
  items: PerformanceObservation[];
  total: number;
  limit: number;
  offset: number;
  measured_page_count?: number;
  field_available_page_count?: number;
  field_available_phone_page_count?: number;
  field_available_desktop_page_count?: number;
};

export type PerformanceRunList = {
  items: PerformanceRun[];
  total: number;
  limit: number;
  offset: number;
};

export type PerformanceRunDetail = PerformanceRun & {
  observations: PerformanceObservationList;
};

export type PerformanceRunPayload = {
  resource_ids: number[];
  providers: Array<"pagespeed" | "crux">;
  pagespeed_strategies: Array<"mobile" | "desktop">;
  crux_form_factors: Array<"PHONE" | "DESKTOP">;
  include_origin_crux: boolean;
  trigger: "site_workspace" | "page_workspace";
};

export type PerformanceMetricPresentation = {
  key: string; label: string; value: number; unit: string; formatted_value: string;
  assessment: "good" | "needs_improvement" | "poor" | null;
  histogram: Array<Record<string, number>>;
};

export type PageSpeedAuditPresentation = {
  audit_id: string; title: string; description: string | null; display_value: string | null;
  score: number | null; savings_ms: number | null; savings_bytes: number | null;
};

export type PerformanceObservationPresentation = {
  observation: PerformanceObservation;
  metrics: PerformanceMetricPresentation[];
  opportunities: PageSpeedAuditPresentation[];
  diagnostics: PageSpeedAuditPresentation[];
  origin_context: PerformanceObservation | null;
  origin_metrics: PerformanceMetricPresentation[];
  presentation_error: string | null;
};
