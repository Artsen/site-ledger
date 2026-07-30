from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
    max_html_response_bytes: int = 2_000_000
    concurrent_requests_per_host: int = 2
    delay_between_requests_ms: int = 0
    user_agent: str = "ArtsenDesignScanner/0.1"
    drop_query_parameters: list[str] = Field(default_factory=list)
    allow_private_networks: bool = False
    max_redirects: int = 10


class ScanCreate(BaseModel):
    starting_url: str
    scope_config: ScopeConfigPayload


class ScanRead(BaseModel):
    id: int
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
    stop_reason: str | None
    fatal_error_message: str | None

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
    response_time_ms: int | None
    fetch_state: str
    error_type: str | None


class PageList(BaseModel):
    items: list[PageRead]
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

    model_config = {"from_attributes": True}
