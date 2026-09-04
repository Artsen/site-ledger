export type EvidenceDomain = "performance" | "accessibility" | "render" | "structured_content";
export type CollectionTargetMode = "missing_current" | "refresh_current";

export type CollectionPlanRequest = {
  evidence_domain: EvidenceDomain;
  target_mode: CollectionTargetMode;
  context: Record<string, unknown>;
};

export type CollectionCoverage = {
  evidence_domain: EvidenceDomain;
  target_mode: CollectionTargetMode;
  context_identity: string;
  context: Record<string, string>;
  active_page_count: number;
  active_page_universe_sha256: string;
  eligible: number;
  covered: number;
  in_flight: number;
  active_collection: number;
  missing: number;
  ineligible: number;
  batch_size: number;
  estimated_batch_count: number;
  collectable: boolean;
  non_collectable_reason: string | null;
};

export type CollectionPlanTarget = {
  id?: number;
  position: number;
  web_resource_id: number;
  requested_url: string;
  selection_reason: CollectionTargetMode;
  latest_compatible_observed_at: string | null;
  target_context?: Record<string, unknown>;
  source_snapshot_id: number | null;
  content_blob_id: number | null;
  created_at?: string;
};

export type CollectionPlanPreview = CollectionCoverage & {
  targets: CollectionPlanTarget[];
  target_total: number;
  limit: number;
  offset: number;
};

export type CollectionPlanBatch = {
  id: number;
  position: number;
  target_start_position: number;
  target_count: number;
  child_kind: string;
  status: string;
  processed_target_count: number;
  background_job_id: number | null;
  performance_run_id: number | null;
  accessibility_run_id: number | null;
  render_run_id: number | null;
  created_at: string;
};

export type CollectionPlan = {
  id: number;
  website_property_id: number;
  planner_version: string;
  evidence_domain: EvidenceDomain;
  target_mode: CollectionTargetMode;
  context_identity: string;
  context: Record<string, string>;
  active_page_count: number;
  eligible_count: number;
  covered_count_at_creation: number;
  in_flight_count_at_creation: number;
  active_collection_count_at_creation: number;
  missing_count_at_creation: number;
  selection_reason_counts: Record<string, number>;
  ineligible_count_at_creation: number;
  target_count: number;
  batch_size: number;
  batch_count: number;
  target_selection_sha256: string;
  cancellation_requested_at: string | null;
  created_at: string;
  status: string;
  progress: {
    batch_count: number;
    queued_batches: number;
    running_batches: number;
    completed_batches: number;
    failed_batches: number;
    cancelled_batches: number;
    target_count: number;
    processed_target_count: number;
  };
  batches: CollectionPlanBatch[];
};

export type CollectionPlanList = {
  items: CollectionPlan[];
  total: number;
  limit: number;
  offset: number;
};

export type CollectionPlanTargetList = {
  items: CollectionPlanTarget[];
  total: number;
  limit: number;
  offset: number;
};
