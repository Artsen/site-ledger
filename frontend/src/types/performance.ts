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
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_summary: string | null;
  job_id: number | null;
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
