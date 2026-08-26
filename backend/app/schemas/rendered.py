from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RenderCapabilitiesRead(BaseModel):
    defaults: dict[str, Any]
    limits: dict[str, dict[str, float]]
    supported_modes: list[str]
    browser_engine: str
    artifact_types: list[str]
    allowed_request_methods: list[str]
    service_workers: str


class RenderedArtifactRead(BaseModel):
    id: int
    artifact_type: str
    width: int | None
    height: int | None
    media_type: str
    raw_byte_size: int
    stored_byte_size: int
    sha256: str
    metadata_json: dict[str, Any]


class RenderedObservationRead(BaseModel):
    id: int
    snapshot_id: int
    capture_state: str
    started_at: datetime | None
    finished_at: datetime | None
    requested_url: str
    final_url: str | None
    navigation_http_status: int | None
    document_title: str | None
    browser_engine: str
    browser_version: str | None
    playwright_version: str | None
    renderer_version: str
    browser_policy_version: str
    capture_schema_version: str
    user_agent: str | None
    viewport_width: int
    viewport_height: int
    device_scale_factor: float
    locale: str
    timezone_id: str
    color_scheme: str
    reduced_motion: str
    readiness_state: str | None
    load_event_reached: bool
    fonts_ready_reached: bool
    duration_ms: int | None
    configuration_fingerprint: str
    network_entry_count: int
    blocked_request_count: int
    console_message_count: int
    page_error_count: int
    warning_count: int
    network_truncated: bool
    console_truncated: bool
    page_errors_truncated: bool
    total_encoded_network_bytes: int
    error_type: str | None
    error_message: str | None
    warnings_json: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[RenderedArtifactRead] = Field(default_factory=list)


class RenderedNetworkEntryRead(BaseModel):
    id: int
    sequence: int
    redacted_url: str
    url_sha256: str
    method: str
    resource_type: str | None
    is_main_navigation: bool
    is_navigation_request: bool
    request_started_offset_ms: int | None
    duration_ms: int | None
    response_status: int | None
    response_status_text: str | None
    response_mime_type: str | None
    encoded_data_length: int | None
    request_headers_json: dict[str, str]
    response_headers_json: dict[str, str]
    failure_reason: str | None
    blocked_by_policy: bool
    policy_reason: str | None
    model_config = {"from_attributes": True}


class RenderedConsoleMessageRead(BaseModel):
    id: int
    sequence: int
    message_type: str
    text: str
    source_url: str | None
    line_number: int | None
    column_number: int | None
    timestamp_offset_ms: int | None
    model_config = {"from_attributes": True}


class RenderedPageErrorRead(BaseModel):
    id: int
    sequence: int
    error_name: str | None
    message: str
    stack: str | None
    source_url: str | None
    timestamp_offset_ms: int | None
    model_config = {"from_attributes": True}


class RenderedEventList(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


class RenderedObservationIndexItem(BaseModel):
    id: int
    snapshot_id: int
    resource_id: int
    page_title: str | None
    static_final_url: str | None
    browser_final_url: str | None
    capture_state: str
    static_http_status: int | None
    navigation_http_status: int | None
    error_type: str | None
    error_message: str | None
    duration_ms: int | None
    warning_count: int
    blocked_request_count: int
    console_message_count: int
    page_error_count: int
    has_viewport_screenshot: bool
    has_full_page_screenshot: bool
    has_rendered_dom: bool
    finished_at: datetime | None


class RenderedObservationSummary(BaseModel):
    successful_renders: int
    no_content_responses: int
    redirect_responses: int
    http_error_responses: int
    rate_limited: int
    skipped_after_throttling: int
    technical_failures: int
    artifacts_retained: int


class RenderedObservationIndexList(BaseModel):
    items: list[RenderedObservationIndexItem]
    total: int
    limit: int
    offset: int
    summary: RenderedObservationSummary
