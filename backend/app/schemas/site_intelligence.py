from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CoverageRead(BaseModel):
    observed: int
    eligible: int
    ratio: float | None


class EvidenceClock(BaseModel):
    latest_observed_at: datetime | None = None
    latest_completed_at: datetime | None = None
    oldest_current_observation_at: datetime | None = None
    newest_current_observation_at: datetime | None = None
    source_run_id: int | None = None
    source_scan_id: int | None = None
    source_comparison_id: int | None = None
    source_status: str | None = None


class PagePopulationRead(BaseModel):
    active_page_total: int
    suppressed_page_total: int
    workspace_page_total: int
    workflow_counts: dict[str, int] = Field(default_factory=dict)


class ScanIntelligenceRead(BaseModel):
    present: bool
    id: int | None = None
    status: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    discovered_count: int = 0
    fetched_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    stop_reason: str | None = None
    fatal_error_message: str | None = None
    active_page_observed: CoverageRead
    active_page_fetched: CoverageRead
    clock: EvidenceClock


class ComparisonIntelligenceRead(BaseModel):
    present: bool
    comparison_id: int | None = None
    build_id: int | None = None
    baseline_scan_id: int | None = None
    target_scan_id: int | None = None
    comparison_version: str | None = None
    algorithm_identity: str | None = None
    page_counts: dict[str, Any] = Field(default_factory=dict)
    resource_counts: dict[str, Any] = Field(default_factory=dict)
    link_counts: dict[str, Any] = Field(default_factory=dict)
    clock: EvidenceClock


class StructuredContentIntelligenceRead(BaseModel):
    extractor_version: str
    extractor_config_version: str
    markdown_renderer_version: str
    active_pages: int
    eligible_retained_html: int
    ready: int
    partial: int
    unavailable: int
    not_prepared: int
    ineligible: int
    coverage: CoverageRead
    clock: EvidenceClock


class RenderLatestRunRead(BaseModel):
    present: bool
    id: int | None = None
    status: str | None = None
    target_count: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RenderIntelligenceRead(BaseModel):
    latest_run: RenderLatestRunRead
    retained_coverage: CoverageRead
    successful: int
    no_content: int
    redirect: int
    http_error: int
    rate_limited: int
    not_attempted_host_throttled: int
    technical_failure: int
    clock: EvidenceClock


class PerformanceContextRead(BaseModel):
    provider: str
    dimension: str
    target_kind: str
    provider_adapter_version: str
    normalization_version: str
    ready: int
    unavailable: int
    failed: int
    coverage: CoverageRead
    clock: EvidenceClock


class PerformanceIntelligenceRead(BaseModel):
    contexts: list[PerformanceContextRead] = Field(default_factory=list)
    latest_run_id: int | None = None
    latest_run_status: str | None = None
    clock: EvidenceClock


class AccessibilityIntelligenceRead(BaseModel):
    coverage: CoverageRead
    ready_pages: int
    failed_pages: int
    pages_with_violations: int
    violation_rules: int
    affected_nodes: int
    needs_review_rules: int
    clock: EvidenceClock


class SourcesIntelligenceRead(BaseModel):
    active_source_count: int
    inactive_source_count: int
    current_inventory_count: int
    suppressed_inventory_count: int
    latest_refresh_status: str | None = None
    latest_refresh_finished_at: datetime | None = None


class FindingsIntelligenceRead(BaseModel):
    detected: int
    unknown: int
    acknowledged_detected: int
    unresolved_total: int
    latest_evaluation_id: int | None = None
    latest_evidence_horizon_at: datetime | None = None
    latest_evaluation_completed_at: datetime | None = None


class ActiveJobRead(BaseModel):
    id: int
    job_type: str
    status: Literal["queued", "running"]
    current_operation: str | None
    progress_current: int | None
    progress_total: int | None
    progress_unit: str | None
    created_at: datetime
    started_at: datetime | None


class ActivityIntelligenceRead(BaseModel):
    active_job_count: int
    queued_count: int
    running_count: int
    jobs: list[ActiveJobRead] = Field(default_factory=list)


class SiteIntelligenceRead(BaseModel):
    site_id: int
    page_population: PagePopulationRead
    scan: ScanIntelligenceRead
    comparison: ComparisonIntelligenceRead
    structured_content: StructuredContentIntelligenceRead
    render: RenderIntelligenceRead
    performance: PerformanceIntelligenceRead
    accessibility: AccessibilityIntelligenceRead
    sources: SourcesIntelligenceRead
    findings: FindingsIntelligenceRead
    activity: ActivityIntelligenceRead
