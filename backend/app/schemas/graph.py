from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.scans import LinkRead


class GraphScanRead(BaseModel):
    id: int
    starting_url: str
    status: str
    website_property_id: int | None = None
    website_property_name: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class GraphNodeRead(BaseModel):
    id: str
    kind: Literal["page", "discovered"]
    snapshot_id: int | None = None
    resource_id: int | None = None
    requested_url: str | None = None
    final_url: str | None = None
    page_title: str | None = None
    host: str | None = None
    path: str | None = None
    http_status: int | None = None
    fetch_state: str | None = None
    error_type: str | None = None
    crawl_depth: int | None = None
    content_type: str | None = None
    response_time_ms: int | None = None
    inbound_occurrence_count: int = 0
    inbound_source_page_count: int = 0
    outbound_occurrence_count: int = 0
    outbound_target_page_count: int = 0
    is_scan_seed: bool = False
    seed_origin_count: int = 0
    is_starting_url: bool = False
    redirects: bool = False
    canonical_url: str | None = None
    category: str | None = None


class GraphEdgeRead(BaseModel):
    id: str
    source: str
    target: str
    source_snapshot_id: int
    target_snapshot_id: int | None = None
    target_resource_id: int | None = None
    occurrence_count: int
    unique_anchor_text_count: int
    nofollow_occurrence_count: int
    follow_occurrence_count: int
    empty_anchor_occurrence_count: int
    is_self_link: bool
    sample_anchor_texts: list[str]
    first_discovered_at: datetime | None
    last_discovered_at: datetime | None
    scope_decisions: dict[str, int]
    role_counts: dict[str, int] = Field(default_factory=dict)
    dom_regions: dict[str, int] = Field(default_factory=dict)


class GraphSummaryRead(BaseModel):
    total_available_nodes: int
    total_available_edges: int
    returned_nodes: int
    returned_edges: int
    fetched_nodes: int
    unfetched_nodes: int
    error_nodes: int
    self_link_edges: int
    total_occurrences: int
    truncated: bool
    truncation_reasons: list[str]
    focused: bool = False
    focus_snapshot_id: int | None = None
    focus_hops: int | None = None


class GraphResponse(BaseModel):
    scan: GraphScanRead
    summary: GraphSummaryRead
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]
    effective_filters: dict[str, str | int | bool | None]


class GraphCapabilitiesRead(BaseModel):
    default_node_limit: int
    maximum_node_limit: int
    default_edge_limit: int
    maximum_edge_limit: int
    default_focus_hops: int
    maximum_focus_hops: int
    sample_anchor_limit: int
    occurrence_page_default: int
    occurrence_page_maximum: int
    supported_status_filters: list[str]
    supported_error_filters: list[str]
    supported_node_size_modes: list[str]
    supported_node_category_modes: list[str]


class GraphEdgeOccurrenceRead(LinkRead):
    source_snapshot_id: int
    target_snapshot_id: int | None = None
    is_self_link: bool


class GraphEdgeOccurrenceList(BaseModel):
    items: list[GraphEdgeOccurrenceRead]
    total: int
    limit: int
    offset: int
    edge: GraphEdgeRead | None = None


GraphStatusFilter = Literal["any", "2xx", "3xx", "4xx", "5xx", "none"]
GraphErrorStateFilter = Literal["any", "with_errors", "without_errors"]
