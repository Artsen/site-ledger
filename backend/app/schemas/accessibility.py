from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AccessibilityProfile = Literal["desktop", "mobile"]
OBSERVABILITY_REQUEST_PAGE_LIMIT = 250


def _default_profiles() -> list[AccessibilityProfile]:
    return ["desktop", "mobile"]


class AccessibilityRunCreate(BaseModel):
    resource_ids: list[int] = Field(min_length=1, max_length=OBSERVABILITY_REQUEST_PAGE_LIMIT)
    profiles: list[AccessibilityProfile] = Field(default_factory=_default_profiles)
    trigger: Literal["site_workspace", "page_workspace"] = "site_workspace"

    @model_validator(mode="after")
    def validate_configuration(self) -> "AccessibilityRunCreate":
        if len(self.resource_ids) != len(set(self.resource_ids)):
            raise ValueError("resource_ids cannot contain duplicates.")
        if not self.profiles:
            raise ValueError("Select at least one audit profile.")
        if len(self.profiles) != len(set(self.profiles)):
            raise ValueError("profiles cannot contain duplicates.")
        return self


class AccessibilityCapabilities(BaseModel):
    axe_core_version: str
    detector_bundle_sha256: str
    integration_version: str
    normalization_version: str
    ruleset_profile: str
    ruleset_rule_count: int
    ruleset_sha256: str
    default_page_limit: int
    hard_page_limit: int
    absolute_page_limit: int
    max_audit_count: int
    profiles: dict[str, dict[str, Any]]


class AccessibilityRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_property_id: int
    status: str
    trigger: str
    configuration_json: dict[str, Any]
    target_count: int
    observation_count: int
    completed_count: int
    ready_count: int
    failed_count: int
    axe_core_version: str
    detector_bundle_sha256: str
    integration_version: str
    normalization_version: str
    ruleset_profile: str
    ruleset_rule_count: int
    ruleset_sha256: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_summary: str | None
    job_id: int | None = None
    presentation_status: str | None = None
    retained_observation_count: int = 0
    deleted_observation_count: int = 0
    retained_ready_count: int = 0
    retained_failed_count: int = 0
    deleted_ready_count: int = 0
    deleted_failed_count: int = 0


class AccessibilityObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    accessibility_run_id: int
    website_property_id: int
    web_resource_id: int
    requested_url: str
    final_url: str | None
    profile: str
    outcome: str
    observed_at: datetime
    axe_core_version: str
    detector_bundle_sha256: str
    integration_version: str
    normalization_version: str
    ruleset_profile: str
    ruleset_sha256: str
    browser_engine: str
    browser_version: str | None
    playwright_version: str | None
    profile_json: dict[str, Any]
    violation_rule_count: int
    violation_node_count: int
    incomplete_rule_count: int
    incomplete_node_count: int
    pass_rule_count: int
    inapplicable_rule_count: int
    normalized_sha256: str | None
    error_type: str | None
    error_message: str | None
    page_url: str | None = None
    payload_sha256: str | None = None
    payload_raw_byte_size: int | None = None
    payload_stored_byte_size: int | None = None


class AccessibilityRuleRead(BaseModel):
    id: int
    accessibility_observation_id: int
    position: int
    rule_id: str
    result_type: str
    impact: str | None
    description: str
    help: str
    help_url: str | None
    tags_json: list[str]
    node_count: int
    rule_evidence_sha256: str


class AccessibilityNodeRead(BaseModel):
    id: int
    position: int
    impact: str | None
    target_json: list[Any]
    html_snippet: str
    html_original_length: int
    html_truncated: bool
    failure_summary: str
    node_evidence_sha256: str


class AccessibilityRuleList(BaseModel):
    items: list[AccessibilityRuleRead]
    total: int
    limit: int
    offset: int


class AccessibilityNodeList(BaseModel):
    items: list[AccessibilityNodeRead]
    total: int
    limit: int
    offset: int


class AccessibilityObservationList(BaseModel):
    items: list[AccessibilityObservationRead]
    total: int
    limit: int
    offset: int


class AccessibilityRunList(BaseModel):
    items: list[AccessibilityRunRead]
    total: int
    limit: int
    offset: int


class AccessibilityRunDetail(AccessibilityRunRead):
    observations: AccessibilityObservationList


class AccessibilitySummary(BaseModel):
    pages_audited: int
    profiles_audited: int
    pages_with_violations: int
    violation_rules: int
    affected_nodes: int
    needs_review_rules: int
    impact_counts: dict[str, int]
    failed_latest: int
    latest_observed_at: datetime | None


class AccessibilityPageSummary(BaseModel):
    page_id: int
    page_url: str
    last_audited_at: datetime
    desktop_outcome: str | None
    mobile_outcome: str | None
    desktop_violations: int
    mobile_violations: int
    critical_rules: int
    serious_rules: int
    needs_review_rules: int


class AccessibilityPageSummaryList(BaseModel):
    items: list[AccessibilityPageSummary]
    total: int
    limit: int
    offset: int


class AccessibilityRuleAggregate(BaseModel):
    rule_id: str
    result_type: str
    impact: str | None
    help: str
    help_url: str | None
    tags: list[str]
    pages_affected: int
    affected_nodes: int
    profiles: list[str]


class AccessibilityRuleAggregateList(BaseModel):
    items: list[AccessibilityRuleAggregate]
    total: int
    limit: int
    offset: int


class AccessibilityRuleOccurrence(BaseModel):
    observation_id: int
    page_id: int
    page_url: str
    profile: str
    observed_at: datetime
    result_type: str
    impact: str | None
    node: AccessibilityNodeRead


class AccessibilityRuleDetail(BaseModel):
    rule_id: str
    help: str
    description: str
    help_url: str | None
    tags: list[str]
    impact: str | None
    pages_affected: int
    affected_nodes: int
    occurrences: list[AccessibilityRuleOccurrence]
    total: int
    limit: int
    offset: int


class AccessibilityObservationDeletePreview(BaseModel):
    can_delete: bool
    reason: str | None = None
    observation_id: int
    run_id: int
    profile: str
    outcome: str
    observed_at: datetime
    requested_url: str
    violation_rule_count: int
    incomplete_rule_count: int
    rule_rows_deleted: int
    node_rows_deleted: int
    payload_present: bool
    payload_shared: bool
    payload_reference_count: int
    payload_raw_bytes: int
    payload_stored_bytes: int
    raw_bytes_reclaimable: int
    stored_bytes_reclaimable: int


class AccessibilityRunDeletePreview(BaseModel):
    can_delete: bool
    reason: str | None = None
    run_id: int
    status: str
    created_at: datetime
    finished_at: datetime | None
    completed_count: int
    ready_count: int
    failed_count: int
    retained_observation_count: int
    deleted_observation_count: int
    rule_rows_removed: int
    node_rows_removed: int
    payload_blobs_referenced: int
    exclusive_payload_blobs: int
    shared_payload_blobs: int
    raw_bytes_reclaimable: int
    stored_bytes_reclaimable: int
    background_jobs_removed: int
    job_events_removed: int


class AccessibilitySiteDeletePreview(BaseModel):
    can_delete: bool
    reason: str | None = None
    site_id: int
    runs: int
    retained_observations: int
    already_deleted_observations: int
    rule_rows_removed: int
    node_rows_removed: int
    background_jobs_removed: int
    job_events_removed: int
    payload_blobs_referenced: int
    exclusive_payload_blobs: int
    shared_payload_blobs: int
    raw_bytes_reclaimable: int
    stored_bytes_reclaimable: int


class AccessibilityDeleteConfirmation(BaseModel):
    confirmation: str


class AccessibilityDeleteResult(BaseModel):
    deleted_observation_id: int | None = None
    deleted_run_id: int | None = None
    purged_site_id: int | None = None
    runs_deleted: int = 0
    observations_deleted: int = 0
    rule_rows_deleted: int = 0
    node_rows_deleted: int = 0
    background_jobs_deleted: int = 0
    job_events_deleted: int = 0
    payload_blob_records_deleted: int = 0
    payload_blob_files_deleted: int = 0
    raw_bytes_reclaimed: int = 0
    stored_bytes_reclaimed: int = 0
    warnings: list[str] = Field(default_factory=list)
