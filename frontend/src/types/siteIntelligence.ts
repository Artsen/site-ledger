export type EvidenceCoverage = {
  observed: number;
  eligible: number;
  ratio: number | null;
};

export type EvidenceClock = {
  latest_observed_at: string | null;
  latest_completed_at: string | null;
  oldest_current_observation_at: string | null;
  newest_current_observation_at: string | null;
  source_run_id: number | null;
  source_scan_id: number | null;
  source_comparison_id: number | null;
  source_status: string | null;
};

export type SiteIntelligence = {
  site_id: number;
  page_population: {
    active_page_total: number;
    suppressed_page_total: number;
    workspace_page_total: number;
    workflow_counts: Record<string, number>;
  };
  scan: {
    present: boolean;
    id: number | null;
    status: string | null;
    created_at: string | null;
    started_at: string | null;
    finished_at: string | null;
    discovered_count: number;
    fetched_count: number;
    failed_count: number;
    skipped_count: number;
    stop_reason: string | null;
    fatal_error_message: string | null;
    active_page_observed: EvidenceCoverage;
    active_page_fetched: EvidenceCoverage;
    clock: EvidenceClock;
  };
  comparison: {
    present: boolean;
    comparison_id: number | null;
    build_id: number | null;
    baseline_scan_id: number | null;
    target_scan_id: number | null;
    comparison_version: string | null;
    algorithm_identity: string | null;
    page_counts: Record<string, unknown>;
    resource_counts: Record<string, unknown>;
    link_counts: Record<string, unknown>;
    clock: EvidenceClock;
  };
  structured_content: {
    extractor_version: string;
    extractor_config_version: string;
    markdown_renderer_version: string;
    active_pages: number;
    eligible_retained_html: number;
    ready: number;
    partial: number;
    unavailable: number;
    not_prepared: number;
    ineligible: number;
    coverage: EvidenceCoverage;
    clock: EvidenceClock;
  };
  render: {
    latest_run: {
      present: boolean;
      id: number | null;
      status: string | null;
      target_count: number;
      created_at: string | null;
      started_at: string | null;
      finished_at: string | null;
    };
    retained_coverage: EvidenceCoverage;
    successful: number;
    no_content: number;
    redirect: number;
    http_error: number;
    rate_limited: number;
    not_attempted_host_throttled: number;
    technical_failure: number;
    clock: EvidenceClock;
  };
  performance: {
    contexts: Array<{
      provider: string;
      dimension: string;
      target_kind: string;
      provider_adapter_version: string;
      normalization_version: string;
      ready: number;
      unavailable: number;
      failed: number;
      coverage: EvidenceCoverage;
      clock: EvidenceClock;
    }>;
    latest_run_id: number | null;
    latest_run_status: string | null;
    clock: EvidenceClock;
  };
  accessibility: {
    coverage: EvidenceCoverage;
    ready_pages: number;
    failed_pages: number;
    pages_with_violations: number;
    violation_rules: number;
    affected_nodes: number;
    needs_review_rules: number;
    clock: EvidenceClock;
  };
  sources: {
    active_source_count: number;
    inactive_source_count: number;
    current_inventory_count: number;
    suppressed_inventory_count: number;
    latest_refresh_status: string | null;
    latest_refresh_finished_at: string | null;
  };
  activity: {
    active_job_count: number;
    queued_count: number;
    running_count: number;
    jobs: Array<{
      id: number;
      job_type: string;
      status: "queued" | "running";
      current_operation: string | null;
      progress_current: number | null;
      progress_total: number | null;
      progress_unit: string | null;
      created_at: string;
      started_at: string | null;
    }>;
  };
};
