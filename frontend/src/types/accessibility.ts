export type AccessibilityProfile = "desktop" | "mobile";

export type AccessibilityCapabilities = {
  axe_core_version: string;
  detector_bundle_sha256: string;
  integration_version: string;
  normalization_version: string;
  ruleset_profile: string;
  ruleset_rule_count: number;
  ruleset_sha256: string;
  default_page_limit: number;
  hard_page_limit: number;
  absolute_page_limit: number;
  max_audit_count: number;
  profiles: Record<string, Record<string, unknown>>;
};

export type AccessibilityRun = {
  id: number;
  website_property_id: number;
  status: string;
  presentation_status: string | null;
  trigger: string;
  configuration_json: { resource_ids: number[]; profiles: AccessibilityProfile[] };
  target_count: number;
  observation_count: number;
  completed_count: number;
  ready_count: number;
  failed_count: number;
  axe_core_version: string;
  detector_bundle_sha256: string;
  integration_version: string;
  normalization_version: string;
  ruleset_profile: string;
  ruleset_rule_count: number;
  ruleset_sha256: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_summary: string | null;
  job_id: number | null;
};

export type AccessibilityObservation = {
  id: number;
  accessibility_run_id: number;
  website_property_id: number;
  web_resource_id: number;
  requested_url: string;
  final_url: string | null;
  profile: AccessibilityProfile;
  outcome: "ready" | "failed";
  observed_at: string;
  axe_core_version: string;
  detector_bundle_sha256: string;
  integration_version: string;
  normalization_version: string;
  ruleset_profile: string;
  ruleset_sha256: string;
  browser_engine: string;
  browser_version: string | null;
  playwright_version: string | null;
  profile_json: Record<string, unknown>;
  violation_rule_count: number;
  violation_node_count: number;
  incomplete_rule_count: number;
  incomplete_node_count: number;
  pass_rule_count: number;
  inapplicable_rule_count: number;
  normalized_sha256: string | null;
  error_type: string | null;
  error_message: string | null;
  page_url: string | null;
  payload_sha256: string | null;
  payload_raw_byte_size: number | null;
  payload_stored_byte_size: number | null;
};

export type AccessibilityObservationList = {
  items: AccessibilityObservation[];
  total: number;
  limit: number;
  offset: number;
};

export type AccessibilityRunList = {
  items: AccessibilityRun[];
  total: number;
  limit: number;
  offset: number;
};

export type AccessibilityRunDetail = AccessibilityRun & {
  observations: AccessibilityObservationList;
};

export type AccessibilityRunPayload = {
  resource_ids: number[];
  profiles: AccessibilityProfile[];
  trigger: "site_workspace" | "page_workspace";
};

export type AccessibilitySummary = {
  pages_audited: number;
  profiles_audited: number;
  pages_with_violations: number;
  violation_rules: number;
  affected_nodes: number;
  needs_review_rules: number;
  impact_counts: Record<string, number>;
  failed_latest: number;
  latest_observed_at: string | null;
};

export type AccessibilityPageSummary = {
  page_id: number;
  page_url: string;
  last_audited_at: string;
  desktop_outcome: string | null;
  mobile_outcome: string | null;
  desktop_violations: number;
  mobile_violations: number;
  critical_rules: number;
  serious_rules: number;
  needs_review_rules: number;
};

export type AccessibilityPageSummaryList = {
  items: AccessibilityPageSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type AccessibilityRuleAggregate = {
  rule_id: string;
  result_type: "violation" | "incomplete";
  impact: string | null;
  help: string;
  help_url: string | null;
  tags: string[];
  pages_affected: number;
  affected_nodes: number;
  profiles: AccessibilityProfile[];
};

export type AccessibilityRuleAggregateList = {
  items: AccessibilityRuleAggregate[];
  total: number;
  limit: number;
  offset: number;
};

export type AccessibilityNode = {
  id: number;
  position: number;
  impact: string | null;
  target_json: unknown[];
  html_snippet: string;
  html_original_length: number;
  html_truncated: boolean;
  failure_summary: string;
  node_evidence_sha256: string;
};

export type AccessibilityRule = {
  id: number; accessibility_observation_id: number; position: number; rule_id: string;
  result_type: "violation" | "incomplete"; impact: string | null; description: string;
  help: string; help_url: string | null; tags_json: string[]; node_count: number;
  rule_evidence_sha256: string;
};

export type AccessibilityRuleList = { items: AccessibilityRule[]; total: number; limit: number; offset: number };
export type AccessibilityNodeList = { items: AccessibilityNode[]; total: number; limit: number; offset: number };

export type AccessibilityRuleDetail = {
  rule_id: string;
  help: string;
  description: string;
  help_url: string | null;
  tags: string[];
  impact: string | null;
  pages_affected: number;
  affected_nodes: number;
  occurrences: Array<{
    observation_id: number;
    page_id: number;
    page_url: string;
    profile: AccessibilityProfile;
    observed_at: string;
    result_type: "violation" | "incomplete";
    impact: string | null;
    node: AccessibilityNode;
  }>;
  total: number;
  limit: number;
  offset: number;
};
