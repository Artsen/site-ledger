export type FindingSitemapRefreshNode = {
  url_source_id: number;
  source_refresh_id: number;
  sitemap_document_type: "urlset" | "sitemapindex" | null;
  status: string;
  membership_materialized: boolean;
  children: FindingSitemapRefreshNode[];
};

export type FindingEvaluation = {
  id: number; website_property_id: number; source_scan_id: number | null;
  evaluator_version: string; detector_bundle_identity: string; input_fingerprint_sha256: string;
  evidence_horizon_at: string; active_page_count: number; active_page_universe_sha256: string;
  status: string; detected_count: number; clear_count: number; unknown_count: number;
  detector_summary_json: Record<string, FindingDetectorSummary>;
  evidence_manifest_json: {
    schema?: string;
    static?: { scan_id?: number };
    sitemap_roots?: Array<{
      url_source_id: number;
      refresh_tree: FindingSitemapRefreshNode | null;
    }>;
  };
  created_finding_count: number; resolved_finding_count: number; reopened_finding_count: number;
  assessment_count: number; evaluation_checksum_sha256: string | null; created_at: string;
  started_at: string | null; finished_at: string | null; failed_at: string | null;
  error_type: string | null; error_message: string | null; background_job_id: number | null;
};

export type FindingDetectorSummary = {
  detector_identity: string; detected: number; clear: number; unknown: number;
  reason_counts: Record<string, number>;
};

export type Finding = {
  id: number; web_resource_id: number; page_url: string; finding_type: string;
  finding_label: string;
  logical_key_version: string; fingerprint_sha256: string;
  condition_state: "detected" | "unknown" | "resolved";
  current_severity: "medium" | "high" | null; first_detected_at: string;
  last_detected_at: string; last_evaluated_evidence_at: string; resolved_at: string | null;
  reopened_at: string | null; acknowledged_at: string | null; current_assessment_id: number | null;
  page_workspace_state: string | null; current_evidence_summary: Record<string, unknown>;
};

export type FindingEvidenceReference = {
  id: number; position: number; role: string;
  evidence_kind: "resource_snapshot" | "resource_occurrence" | "source_entry_observation" | "scan"; evidence_id: number;
  evidence_observed_at: string; metadata_json: Record<string, unknown>; retained: boolean; href: string | null;
};

export type FindingAssessment = {
  id: number; finding_evaluation_id: number; outcome: "detected" | "clear" | "unknown";
  severity: "medium" | "high" | null; evidence_observed_at: string;
  details_json: Record<string, unknown>; assessment_sha256: string; created_at: string;
  evaluation: FindingEvaluation; evidence_references: FindingEvidenceReference[];
};

export type FindingDetail = Finding & {
  website_property_id: number; created_at: string; updated_at: string; assessments: FindingAssessment[];
};

export type FindingList = { items: Finding[]; total: number; limit: number; offset: number };
export type FindingEvaluationList = { items: FindingEvaluation[]; total: number; limit: number; offset: number };

export type FindingResetResult = {
  site_id: number;
  deleted_finding_count: number;
  deleted_assessment_count: number;
  deleted_evidence_reference_count: number;
  deleted_evaluation_count: number;
  deleted_job_count: number;
  deleted_job_event_count: number;
};
