from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.browser.config import DEFAULTS, validate_render_config
from app.schemas.page_workspaces import PageCategoryRead
from app.schemas.projections import ProjectionMetadata


class ScopeConfigPayload(BaseModel):
    allowed_host_patterns: list[str] = Field(default_factory=list)
    excluded_host_patterns: list[str] = Field(default_factory=list)
    included_path_prefixes: list[str] = Field(default_factory=lambda: ["/"])
    excluded_path_prefixes: list[str] = Field(default_factory=list)
    follow_subdomains: bool = False
    max_pages: int = 100
    max_depth: int = 3
    respect_robots_txt: bool = False
    request_timeout_seconds: float = 10
    static_max_attempts: int = Field(default=2, ge=1, le=5)
    static_retry_initial_delay_ms: int = Field(default=500, ge=0, le=60_000)
    static_retry_max_delay_ms: int = Field(default=5000, ge=0, le=60_000)
    max_html_response_bytes: int = 2_000_000
    concurrent_requests_per_host: int = 2
    delay_between_requests_ms: int = 0
    user_agent: str = "WebsiteScanner/0.1"
    drop_query_parameters: list[str] = Field(default_factory=list)
    allow_private_networks: bool = False
    max_redirects: int = 10
    enable_http_revalidation: bool = True
    enable_parse_reuse: bool = True
    render_mode: str = DEFAULTS.render_mode
    render_max_pages: int = DEFAULTS.render_max_pages
    render_viewport_width: int = DEFAULTS.render_viewport_width
    render_viewport_height: int = DEFAULTS.render_viewport_height
    render_device_scale_factor: float = DEFAULTS.render_device_scale_factor
    render_locale: str = DEFAULTS.render_locale
    render_timezone: str = DEFAULTS.render_timezone
    render_color_scheme: str = DEFAULTS.render_color_scheme
    render_reduced_motion: str = DEFAULTS.render_reduced_motion
    render_navigation_timeout_seconds: float = DEFAULTS.render_navigation_timeout_seconds
    render_load_timeout_seconds: float = DEFAULTS.render_load_timeout_seconds
    render_capture_full_page: bool = DEFAULTS.render_capture_full_page
    render_max_full_page_height: int = DEFAULTS.render_max_full_page_height
    render_max_dom_bytes: int = DEFAULTS.render_max_dom_bytes
    render_max_screenshot_bytes: int = DEFAULTS.render_max_screenshot_bytes
    render_max_network_entries: int = DEFAULTS.render_max_network_entries
    render_max_console_entries: int = DEFAULTS.render_max_console_entries
    render_max_page_errors: int = DEFAULTS.render_max_page_errors
    render_max_page_duration_seconds: float = DEFAULTS.render_max_page_duration_seconds
    render_max_total_network_bytes: int = DEFAULTS.render_max_total_network_bytes
    render_max_resource_bytes: int = DEFAULTS.render_max_resource_bytes

    @model_validator(mode="after")
    def validate_rendering(self) -> "ScopeConfigPayload":
        if self.static_retry_initial_delay_ms > self.static_retry_max_delay_ms:
            raise ValueError("static_retry_initial_delay_ms cannot exceed the maximum delay")
        validate_render_config(self.model_dump())
        return self


class ScanCreate(BaseModel):
    starting_url: str
    scope_config: ScopeConfigPayload
    website_property_id: int | None = None


class ScanRead(BaseModel):
    id: int
    website_property_id: int | None = None
    website_property_name: str | None = None
    website_property_base_url: str | None = None
    starting_url: str
    status: str
    scope_config: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    discovered_count: int
    fetched_count: int
    failed_count: int
    skipped_count: int
    queued_count: int
    conditional_request_count: int = 0
    not_modified_count: int = 0
    parse_reuse_count: int = 0
    full_parse_count: int = 0
    network_bytes_transferred: int = 0
    reused_content_bytes: int = 0
    rendered_selected_count: int = 0
    rendered_attempted_count: int = 0
    rendered_completed_count: int = 0
    rendered_failed_count: int = 0
    rendered_skipped_count: int = 0
    rendered_blocked_request_count: int = 0
    rendered_artifact_count: int = 0
    static_request_attempt_count: int = 0
    static_retry_request_count: int = 0
    static_recovered_after_retry_count: int = 0
    static_retry_exhausted_count: int = 0
    static_connection_timeout_count: int = 0
    static_read_timeout_count: int = 0
    static_connection_error_count: int = 0
    html_page_observed_count: int = 0
    resource_observed_count: int = 0
    resource_discovered_count: int = 0
    resource_reference_occurrence_count: int = 0
    stop_reason: str | None
    fatal_error_message: str | None
    note_count: int = 0

    model_config = {"from_attributes": True}


class PageRead(BaseModel):
    id: int
    resource_id: int
    requested_url: str
    final_url: str | None
    http_status: int | None
    title: str | None
    depth: int
    content_type: str | None
    discovery_source: str | None
    inbound_occurrence_count: int
    inbound_source_page_count: int = 0
    response_time_ms: int | None
    fetch_state: str
    error_type: str | None
    retrieval_method: str | None = None
    parse_method: str | None = None
    retrieval_http_status: int | None = None
    reused_from_snapshot_id: int | None = None
    network_bytes_transferred: int | None = None
    rendered_capture_state: str | None = None


class PageList(BaseModel):
    items: list[PageRead]
    total: int
    limit: int
    offset: int
    projection: ProjectionMetadata | None = None


class PersistentPageRead(BaseModel):
    site_page_id: int
    resource_id: int
    normalized_url: str
    host: str
    path: str
    query: str
    owner_label: str | None
    workflow_status: str
    categories: list[PageCategoryRead] = Field(default_factory=list)
    category_count: int = 0
    note_count: int = 0
    associated_at: datetime
    observation_count: int
    first_observed_at: datetime | None
    latest_observed_at: datetime | None
    latest_snapshot_id: int | None
    latest_scan_id: int | None
    latest_http_status: int | None
    latest_title: str | None
    latest_retrieval_method: str | None
    latest_parse_method: str | None
    latest_reused_from_snapshot_id: int | None
    latest_fetch_state: str | None = None
    latest_error_type: str | None = None
    latest_error_message: str | None = None


class PersistentPageList(BaseModel):
    items: list[PersistentPageRead]
    total: int
    limit: int
    offset: int


class PersistentPageDetail(BaseModel):
    page: PersistentPageRead
    site_id: int
    site_name: str


class PageObservationRead(BaseModel):
    snapshot_id: int
    scan_id: int
    site_id: int | None
    site_name: str | None
    scan_created_at: datetime
    scan_status: str
    scan_started_at: datetime | None
    scan_finished_at: datetime | None
    observed_at: datetime | None
    requested_url: str
    final_url: str | None
    http_status: int | None
    retrieval_http_status: int | None
    fetch_state: str
    error_type: str | None
    crawl_depth: int
    response_time_ms: int | None
    content_type: str | None
    raw_html_sha256: str | None
    head_sha256: str | None
    page_title: str | None
    canonical_url: str | None
    retrieval_method: str | None
    parse_method: str | None
    content_blob_id: int | None
    parse_artifact_id: int | None
    reused_from_snapshot_id: int | None
    network_bytes_transferred: int | None
    parser_version: str | None
    rendered_capture_state: str | None = None


class PageObservationList(BaseModel):
    items: list[PageObservationRead]
    total: int
    limit: int
    offset: int


class SnapshotRead(BaseModel):
    id: int
    scan_id: int
    resource_id: int
    requested_url: str
    final_url: str | None
    http_status: int | None
    content_type: str | None
    encoding: str | None
    crawl_depth: int
    response_time_ms: int | None
    response_headers: dict[str, Any] | None
    redirect_chain: list[dict[str, Any]] | None
    html_raw_byte_size: int | None = None
    html_stored_byte_size: int | None = None
    raw_html_sha256: str | None
    head_sha256: str | None
    page_title: str | None
    html_language: str | None
    meta_description: str | None
    meta_robots: str | None
    canonical_url: str | None
    parsed_head_json: dict[str, Any] | None
    fetch_state: str
    error_type: str | None
    error_message: str | None
    parse_artifact_id: int | None = None
    reused_from_snapshot_id: int | None = None
    retrieval_method: str | None = None
    parse_method: str | None = None
    retrieval_http_status: int | None = None
    retrieval_response_headers: dict[str, Any] | None = None
    network_bytes_transferred: int | None = None
    request_variant_fingerprint: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    cache_control: str | None = None
    vary_header: str | None = None
    representation_kind: str | None = None
    representation_rule: str | None = None
    normalized_mime_type: str | None = None
    file_extension: str | None = None
    content_disposition_filename: str | None = None
    declared_content_length: int | None = None
    response_body_state: str | None = None
    inspected_prefix_byte_count: int = 0
    website_property_id: int | None = None
    website_property_name: str | None = None
    site_page_id: int | None = None
    has_persistent_page: bool = False
    is_html_page: bool = False

    model_config = {"from_attributes": True}


class StaticFetchAttemptRead(BaseModel):
    id: int
    snapshot_id: int
    attempt_number: int
    started_at: datetime
    finished_at: datetime
    requested_url: str
    final_url: str | None
    retrieval_http_status: int | None
    response_time_ms: int | None
    outcome: str
    error_type: str | None
    error_message: str | None
    redirect_chain: list[dict[str, Any]]
    network_bytes_transferred: int
    retryable: bool
    retry_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LinkRead(BaseModel):
    id: int
    raw_href: str | None
    resolved_url: str | None
    normalized_target_url: str | None
    target_resource_id: int | None
    anchor_text: str | None
    title: str | None
    aria_label: str | None
    rel: str | None
    target: str | None
    dom_path: str | None
    in_scope: bool
    scope_decision: str
    exclusion_reason: str | None
    link_role: str | None = None
    link_role_label: str = "Unclassified legacy link"
    link_role_rule: str | None = None
    link_context_json: dict[str, Any] | None = None
    discovered_at: datetime

    model_config = {"from_attributes": True}


class OutgoingLinkSummary(BaseModel):
    total_occurrences: int
    nofollow_occurrences: int
    in_scope_occurrences: int
    role_counts: dict[str, int] = Field(default_factory=dict)


class OutgoingLinkList(BaseModel):
    items: list[LinkRead]
    total: int
    limit: int
    offset: int
    summary: OutgoingLinkSummary


class InboundLinkRead(BaseModel):
    id: int
    source_snapshot_id: int
    source_resource_id: int
    source_requested_url: str
    source_final_url: str | None
    source_page_title: str | None
    source_http_status: int | None
    source_fetch_state: str
    source_crawl_depth: int
    raw_href: str | None
    resolved_url: str | None
    normalized_target_url: str | None
    anchor_text: str | None
    title: str | None
    aria_label: str | None
    rel: str | None
    target: str | None
    dom_path: str | None
    in_scope: bool
    scope_decision: str
    exclusion_reason: str | None
    link_role: str | None = None
    link_role_label: str = "Unclassified legacy link"
    link_role_rule: str | None = None
    discovered_at: datetime
    is_self_link: bool


class InboundLinkSummary(BaseModel):
    total_occurrences: int
    unique_source_pages: int
    unique_anchor_texts: int
    nofollow_occurrences: int
    self_link_occurrences: int
    role_counts: dict[str, int] = Field(default_factory=dict)


class InboundLinkList(BaseModel):
    items: list[InboundLinkRead]
    total: int
    limit: int
    offset: int
    summary: InboundLinkSummary


class ScanHistory(BaseModel):
    items: list[ScanRead]
    total: int
    limit: int
    offset: int


class ScanDeletePreview(BaseModel):
    scan_id: int
    starting_url: str
    can_delete: bool
    status: str
    snapshots: int
    link_occurrences: int
    resource_reference_occurrences: int = 0
    resources_observed: int = 0
    resources_discovered: int = 0
    unique_resources: int
    html_blobs_referenced: int
    exclusive_html_blobs: int
    shared_html_blobs: int
    html_blobs_deleted: int
    raw_html_bytes_reclaimable: int
    stored_html_bytes_reclaimable: int
    rendered_observations: int = 0
    rendered_artifacts: int = 0
    artifact_blobs_referenced: int = 0
    exclusive_artifact_blobs: int = 0
    shared_artifact_blobs: int = 0
    raw_artifact_bytes_reclaimable: int = 0
    stored_artifact_bytes_reclaimable: int = 0
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ScanDeleteResult(BaseModel):
    deleted_scan_id: int
    snapshots_deleted: int
    link_occurrences_deleted: int
    resource_reference_occurrences_deleted: int = 0
    resources_deleted: int
    html_blob_records_deleted: int
    html_blob_files_deleted: int
    html_blobs_deleted: int
    raw_html_bytes_reclaimed: int
    stored_html_bytes_reclaimed: int
    rendered_observations_deleted: int = 0
    rendered_artifacts_deleted: int = 0
    artifact_blob_records_deleted: int = 0
    artifact_blob_files_deleted: int = 0
    raw_artifact_bytes_reclaimed: int = 0
    stored_artifact_bytes_reclaimed: int = 0
    warnings: list[str] = Field(default_factory=list)
