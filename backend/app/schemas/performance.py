from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PerformanceProvider = Literal["pagespeed", "crux"]
PageSpeedStrategy = Literal["mobile", "desktop"]
CruxFormFactor = Literal["PHONE", "DESKTOP"]


def _default_providers() -> list[PerformanceProvider]:
    return ["pagespeed", "crux"]


def _default_strategies() -> list[PageSpeedStrategy]:
    return ["mobile", "desktop"]


def _default_form_factors() -> list[CruxFormFactor]:
    return ["PHONE", "DESKTOP"]


class PerformanceRunCreate(BaseModel):
    resource_ids: list[int] = Field(min_length=1, max_length=25)
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
