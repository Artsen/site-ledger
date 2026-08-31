from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceDomain = Literal["performance", "accessibility", "render", "structured_content"]
TargetMode = Literal["missing_current"]


class CollectionPlanRequest(BaseModel):
    evidence_domain: EvidenceDomain
    target_mode: TargetMode = "missing_current"
    context: dict[str, Any] = Field(default_factory=dict)


class CollectionPreviewTarget(BaseModel):
    position: int
    web_resource_id: int
    requested_url: str
    selection_reason: str
    target_context: dict[str, Any] = Field(default_factory=dict)
    source_snapshot_id: int | None = None
    content_blob_id: int | None = None


class CollectionCoverageRead(BaseModel):
    evidence_domain: EvidenceDomain
    target_mode: TargetMode
    context_identity: str
    context: dict[str, Any]
    active_page_count: int
    active_page_universe_sha256: str
    eligible: int
    covered: int
    in_flight: int
    missing: int
    ineligible: int
    batch_size: int
    estimated_batch_count: int
    collectable: bool
    non_collectable_reason: str | None = None


class CollectionPlanPreview(CollectionCoverageRead):
    targets: list[CollectionPreviewTarget]
    target_total: int
    limit: int
    offset: int


class CollectionPlanBatchRead(BaseModel):
    id: int
    position: int
    target_start_position: int
    target_count: int
    child_kind: str
    status: str
    processed_target_count: int
    background_job_id: int | None
    performance_run_id: int | None
    accessibility_run_id: int | None
    render_run_id: int | None
    created_at: datetime


class CollectionPlanProgress(BaseModel):
    batch_count: int
    queued_batches: int
    running_batches: int
    completed_batches: int
    failed_batches: int
    cancelled_batches: int
    target_count: int
    processed_target_count: int


class CollectionPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_property_id: int
    planner_version: str
    evidence_domain: EvidenceDomain
    target_mode: TargetMode
    context_identity: str
    context: dict[str, Any]
    active_page_count: int
    active_page_universe_sha256: str
    eligible_count: int
    covered_count_at_creation: int
    in_flight_count_at_creation: int
    ineligible_count_at_creation: int
    target_count: int
    batch_size: int
    batch_count: int
    target_selection_sha256: str
    cancellation_requested_at: datetime | None
    created_at: datetime
    status: str
    progress: CollectionPlanProgress
    batches: list[CollectionPlanBatchRead] = Field(default_factory=list)


class CollectionPlanList(BaseModel):
    items: list[CollectionPlanRead]
    total: int
    limit: int
    offset: int


class CollectionPlanTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    web_resource_id: int
    requested_url: str
    selection_reason: str
    target_context: dict[str, Any]
    source_snapshot_id: int | None
    content_blob_id: int | None
    created_at: datetime


class CollectionPlanTargetList(BaseModel):
    items: list[CollectionPlanTargetRead]
    total: int
    limit: int
    offset: int
