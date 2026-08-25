from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PerformanceProvider = Literal["pagespeed", "crux"]
PageSpeedStrategy = Literal["mobile", "desktop"]
CruxFormFactor = Literal["PHONE", "DESKTOP"]
OBSERVABILITY_REQUEST_PAGE_LIMIT = 250


def _default_providers() -> list[PerformanceProvider]:
    return ["pagespeed", "crux"]


def _default_strategies() -> list[PageSpeedStrategy]:
    return ["mobile", "desktop"]


def _default_form_factors() -> list[CruxFormFactor]:
    return ["PHONE", "DESKTOP"]


class PerformanceRunCreate(BaseModel):
    resource_ids: list[int] = Field(min_length=1, max_length=OBSERVABILITY_REQUEST_PAGE_LIMIT)
    providers: list[PerformanceProvider] = Field(default_factory=_default_providers)
    pagespeed_strategies: list[PageSpeedStrategy] = Field(default_factory=_default_strategies)
    crux_form_factors: list[CruxFormFactor] = Field(default_factory=_default_form_factors)
    include_origin_crux: bool = True
    trigger: Literal["site_workspace", "page_workspace"] = "site_workspace"

    @model_validator(mode="after")
    def validate_configuration(self) -> "PerformanceRunCreate":
        for label, values in (
            ("resource_ids", self.resource_ids),
            ("providers", self.providers),
            ("pagespeed_strategies", self.pagespeed_strategies),
            ("crux_form_factors", self.crux_form_factors),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} cannot contain duplicates.")
        if not self.providers:
            raise ValueError("Select at least one provider.")
        if "pagespeed" in self.providers and not self.pagespeed_strategies:
            raise ValueError("Select at least one PageSpeed strategy.")
        if "crux" in self.providers and not self.crux_form_factors:
            raise ValueError("Select at least one CrUX form factor.")
        return self


class PerformanceProviderState(BaseModel):
    configured: bool
    adapter_version: str


class PerformanceProviderCapabilities(BaseModel):
    pagespeed: PerformanceProviderState
    crux: PerformanceProviderState
    normalization_version: str
    default_page_limit: int
    hard_page_limit: int
    absolute_page_limit: int
    max_provider_requests: int
    crux_queries_per_minute: int


class PerformanceRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_property_id: int
    status: str
    trigger: str
    configuration_json: dict[str, Any]
    target_count: int
    request_count: int
    completed_count: int
    ready_count: int
    unavailable_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_summary: str | None
    job_id: int | None = None
    presentation_status: str | None = None
    retained_observation_count: int = 0
    deleted_observation_count: int = 0
    retained_ready_count: int = 0
    retained_unavailable_count: int = 0
    retained_failed_count: int = 0
    deleted_ready_count: int = 0
    deleted_unavailable_count: int = 0
    deleted_failed_count: int = 0


class PerformanceRunList(BaseModel):
    items: list[PerformanceRunRead]
    total: int
    limit: int
    offset: int


class PerformanceObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    performance_run_id: int
    website_property_id: int
    web_resource_id: int | None
    provider: str
    provider_adapter_version: str
    normalization_version: str
    target_kind: str
    requested_target: str
    provider_target: str | None
    dimension: str
    outcome: str
    metrics_json: dict[str, Any]
    normalized_sha256: str | None
    provider_analysis_at: datetime | None
    provider_period_json: dict[str, Any] | None
    provider_product_version: str | None
    observed_at: datetime
    error_type: str | None
    error_message: str | None
    page_url: str | None = None
    payload_sha256: str | None = None
    payload_raw_byte_size: int | None = None
    payload_stored_byte_size: int | None = None


class PerformanceObservationList(BaseModel):
    items: list[PerformanceObservationRead]
    total: int
    limit: int
    offset: int


class PerformanceRunDetail(PerformanceRunRead):
    observations: PerformanceObservationList


class PerformanceLatestList(BaseModel):
    items: list[PerformanceObservationRead]
    total: int
    limit: int
    offset: int
    measured_page_count: int
    field_available_page_count: int
    field_available_phone_page_count: int
    field_available_desktop_page_count: int


class PerformanceMetricPresentation(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    formatted_value: str
    assessment: Literal["good", "needs_improvement", "poor"] | None = None
    histogram: list[dict[str, Any]] = Field(default_factory=list)


class PageSpeedAuditPresentation(BaseModel):
    audit_id: str
    title: str
    description: str | None = None
    display_value: str | None = None
    score: float | None = None
    savings_ms: float | None = None
    savings_bytes: float | None = None


class PerformanceObservationPresentation(BaseModel):
    observation: PerformanceObservationRead
    metrics: list[PerformanceMetricPresentation]
    opportunities: list[PageSpeedAuditPresentation] = Field(default_factory=list)
    diagnostics: list[PageSpeedAuditPresentation] = Field(default_factory=list)
    origin_context: PerformanceObservationRead | None = None
    origin_metrics: list[PerformanceMetricPresentation] = Field(default_factory=list)
    presentation_error: str | None = None


class PerformanceObservationDeletePreview(BaseModel):
    can_delete: bool
    reason: str | None = None
    observation_id: int
    run_id: int
    provider: str
    dimension: str
    outcome: str
    observed_at: datetime
    target_kind: str
    requested_target: str
    payload_present: bool
    payload_shared: bool
    payload_reference_count: int
    payload_raw_bytes: int
    payload_stored_bytes: int
    raw_bytes_reclaimable: int
    stored_bytes_reclaimable: int


class PerformanceRunDeletePreview(BaseModel):
    can_delete: bool
    reason: str | None = None
    run_id: int
    status: str
    created_at: datetime
    finished_at: datetime | None
    completed_count: int
    ready_count: int
    unavailable_count: int
    failed_count: int
    retained_observation_count: int
    deleted_observation_count: int
    payload_blobs_referenced: int
    exclusive_payload_blobs: int
    shared_payload_blobs: int
    raw_bytes_reclaimable: int
    stored_bytes_reclaimable: int
    background_jobs_removed: int
    job_events_removed: int


class PerformanceSiteDeletePreview(BaseModel):
    can_delete: bool
    reason: str | None = None
    site_id: int
    runs: int
    retained_observations: int
    already_deleted_observations: int
    background_jobs_removed: int
    job_events_removed: int
    payload_blobs_referenced: int
    exclusive_payload_blobs: int
    shared_payload_blobs: int
    raw_bytes_reclaimable: int
    stored_bytes_reclaimable: int


class PerformanceDeleteConfirmation(BaseModel):
    confirmation: str


class PerformanceDeleteResult(BaseModel):
    deleted_observation_id: int | None = None
    deleted_run_id: int | None = None
    purged_site_id: int | None = None
    runs_deleted: int = 0
    observations_deleted: int = 0
    background_jobs_deleted: int = 0
    job_events_deleted: int = 0
    payload_blob_records_deleted: int = 0
    payload_blob_files_deleted: int = 0
    raw_bytes_reclaimed: int = 0
    stored_bytes_reclaimed: int = 0
    warnings: list[str] = Field(default_factory=list)
