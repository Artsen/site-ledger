from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FindingState = Literal["detected", "unknown", "resolved"]
FindingSeverity = Literal["medium", "high"]
AssessmentOutcome = Literal["detected", "clear", "unknown"]


class FindingDetectorSummary(BaseModel):
    detector_identity: str
    detected: int
    clear: int
    unknown: int
    reason_counts: dict[str, int] = Field(default_factory=dict)


class FindingEvaluationRead(BaseModel):
    id: int
    website_property_id: int
    source_scan_id: int | None
    evaluator_version: str
    detector_bundle_identity: str
    input_fingerprint_sha256: str
    evidence_horizon_at: datetime
    active_page_count: int
    active_page_universe_sha256: str
    status: str
    detected_count: int
    clear_count: int
    unknown_count: int
    detector_summary_json: dict[str, FindingDetectorSummary] = Field(default_factory=dict)
    created_finding_count: int
    resolved_finding_count: int
    reopened_finding_count: int
    assessment_count: int
    evaluation_checksum_sha256: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failed_at: datetime | None
    error_type: str | None
    error_message: str | None
    background_job_id: int | None = None

    model_config = {"from_attributes": True}


class FindingEvaluationList(BaseModel):
    items: list[FindingEvaluationRead]
    total: int
    limit: int
    offset: int


class FindingListItem(BaseModel):
    id: int
    web_resource_id: int
    page_url: str
    finding_type: str
    finding_label: str
    logical_key_version: str
    fingerprint_sha256: str
    condition_state: FindingState
    current_severity: FindingSeverity | None
    first_detected_at: datetime
    last_detected_at: datetime
    last_evaluated_evidence_at: datetime
    resolved_at: datetime | None
    reopened_at: datetime | None
    acknowledged_at: datetime | None
    current_assessment_id: int | None
    page_workspace_state: str | None
    current_evidence_summary: dict[str, Any] = Field(default_factory=dict)


class FindingList(BaseModel):
    items: list[FindingListItem]
    total: int
    limit: int
    offset: int


class FindingEvidenceReferenceRead(BaseModel):
    id: int
    position: int
    role: str
    evidence_kind: str
    evidence_id: int
    evidence_observed_at: datetime
    metadata_json: dict[str, Any]
    retained: bool
    href: str | None


class FindingAssessmentRead(BaseModel):
    id: int
    finding_evaluation_id: int
    outcome: AssessmentOutcome
    severity: FindingSeverity | None
    evidence_observed_at: datetime
    details_json: dict[str, Any]
    assessment_sha256: str
    created_at: datetime
    evaluation: FindingEvaluationRead
    evidence_references: list[FindingEvidenceReferenceRead]


class FindingDetail(FindingListItem):
    website_property_id: int
    created_at: datetime
    updated_at: datetime
    assessments: list[FindingAssessmentRead]
