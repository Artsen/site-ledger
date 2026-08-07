from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ScanComparisonCreate(BaseModel):
    baseline_scan_id: int
    target_scan_id: int


class ScanComparisonBuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_comparison_id: int
    comparison_version: str
    algorithm_identity: str
    status: str
    baseline_projection_build_id: int | None
    target_projection_build_id: int | None
    baseline_projection_version: str | None
    target_projection_version: str | None
    baseline_projection_algorithm_identity: str | None
    target_projection_algorithm_identity: str | None
    baseline_projection_checksum: str | None
    target_projection_checksum: str | None
    baseline_scope_fingerprint: str | None
    target_scope_fingerprint: str | None
    baseline_seed_fingerprint: str | None
    target_seed_fingerprint: str | None
    coverage_state: str | None
    warnings_json: list[str]
    validation_json: dict[str, Any]
    comparison_checksum_sha256: str | None
    started_at: datetime | None
    finished_at: datetime | None
    failed_at: datetime | None
    build_duration_ms: int | None
    error_type: str | None
    error_message: str | None
    page_result_count: int
    resource_result_count: int
    link_result_count: int
    created_at: datetime


class ComparisonScanRead(BaseModel):
    id: int
    status: str
    starting_url: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    stop_reason: str | None
    failed_count: int


class ScanComparisonRead(BaseModel):
    id: int
    website_property_id: int
    baseline_scan_id: int
    target_scan_id: int
    current_build_id: int | None
    created_at: datetime
    updated_at: datetime
    baseline_scan: ComparisonScanRead
    target_scan: ComparisonScanRead
    current_build: ScanComparisonBuildRead | None
    active_build: ScanComparisonBuildRead | None = None


class ScanComparisonList(BaseModel):
    items: list[ScanComparisonRead]
    total: int
    limit: int
    offset: int


class ComparisonPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_id: int
    normalized_url: str
    host: str
    path: str
    baseline_page_projection_id: int | None
    target_page_projection_id: int | None
    baseline_snapshot_id: int | None
    target_snapshot_id: int | None
    presence_state: str
    baseline_presence_detail: str
    target_presence_detail: str
    change_state: str
    content_state: str
    head_state: str
    changed_field_count: int
    content_changed: bool
    head_changed: bool
    http_status_changed: bool
    fetch_state_changed: bool
    final_url_changed: bool
    redirect_state_changed: bool
    content_type_changed: bool
    title_changed: bool
    canonical_changed: bool
    robots_changed: bool
    language_changed: bool
    depth_changed: bool
    inbound_links_changed: bool
    outbound_links_changed: bool
    embedded_resources_changed: bool
    rendered_state_changed: bool
    rendered_counts_changed: bool
    baseline_http_status: int | None
    target_http_status: int | None
    baseline_content_hash: str | None
    target_content_hash: str | None
    baseline_head_hash: str | None
    target_head_hash: str | None
    response_time_ms_delta: int | None
    network_bytes_delta: int | None
    raw_html_size_delta: int | None
    stored_html_size_delta: int | None
    outgoing_edges_newly_observed: int
    outgoing_edges_not_observed: int
    outgoing_edges_changed: int
    incoming_edges_newly_observed: int
    incoming_edges_not_observed: int
    incoming_edges_changed: int
    baseline_json: dict[str, Any] | None
    target_json: dict[str, Any] | None


class ComparisonPageList(BaseModel):
    items: list[ComparisonPageRead]
    total: int
    limit: int
    offset: int
    comparison_build_id: int
    comparison_version: str


class ComparisonResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_id: int
    normalized_url: str
    host: str
    path: str
    baseline_snapshot_id: int | None
    target_snapshot_id: int | None
    presence_state: str
    change_state: str
    changed_field_count: int
    baseline_kind: str | None
    target_kind: str | None
    baseline_mime_type: str | None
    target_mime_type: str | None
    baseline_http_status: int | None
    target_http_status: int | None
    status_changed: bool
    observed_state_changed: bool
    occurrence_delta: int | None
    source_page_delta: int | None
    declared_size_delta: int | None
    baseline_json: dict[str, Any] | None
    target_json: dict[str, Any] | None


class ComparisonResourceList(BaseModel):
    items: list[ComparisonResourceRead]
    total: int
    limit: int
    offset: int
    comparison_build_id: int
    comparison_version: str


class ComparisonLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_resource_id: int
    target_resource_id: int
    source_url: str
    target_url: str
    baseline_source_snapshot_id: int | None
    target_source_snapshot_id: int | None
    presence_state: str
    change_state: str
    changed_field_count: int
    baseline_occurrence_count: int
    target_occurrence_count: int
    occurrence_delta: int
    baseline_json: dict[str, Any] | None
    target_json: dict[str, Any] | None


class ComparisonLinkList(BaseModel):
    items: list[ComparisonLinkRead]
    total: int
    limit: int
    offset: int
    comparison_build_id: int
    comparison_version: str


class ScanComparisonOverview(BaseModel):
    comparison: ScanComparisonRead
    summary: dict[str, Any] | None


class OccurrenceDiffRead(BaseModel):
    state: Literal["present_in_both", "newly_observed", "not_observed_in_target"]
    fingerprint: str
    occurrence: dict[str, Any]
    count: int


class OccurrenceDiffList(BaseModel):
    items: list[OccurrenceDiffRead]
    total: int
    limit: int
    offset: int
    compared_baseline_count: int
    compared_target_count: int
    truncated: bool


class SourceDiffRead(BaseModel):
    state: Literal[
        "available",
        "identical",
        "baseline_missing",
        "target_missing",
        "too_large",
        "decoding_failed",
        "truncated",
    ]
    diff_text: str
    input_truncated: bool = False
    output_truncated: bool = False


class PageChangeHistoryItem(BaseModel):
    scan_id: int
    snapshot_id: int
    scan_created_at: datetime
    scan_status: str
    observed_at: datetime | None
    http_status: int | None
    fetch_state: str
    content_hash: str | None
    head_hash: str | None
    title: str | None
    canonical_url: str | None
    robots_directives: str | None
    rendered_state: str | None
    change_label: str
    changed_flags: list[str]
    previous_snapshot_id: int | None
    previous_scan_id: int | None
    intervening_scan_count: int
    intervening_unsuccessful_observation_count: int


class PageChangeHistoryList(BaseModel):
    items: list[PageChangeHistoryItem]
    total: int
    limit: int
    offset: int
