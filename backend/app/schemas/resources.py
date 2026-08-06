from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ResourceInventoryItem(BaseModel):
    resource_id: int
    normalized_url: str
    host: str
    path: str
    file_extension: str | None
    effective_kind: str
    effective_kind_label: str
    classification_source: str
    observed: bool
    discovered_only: bool
    snapshot_id: int | None
    final_url: str | None
    http_status: int | None
    normalized_mime_type: str | None
    content_disposition_filename: str | None
    declared_content_length: int | None
    network_bytes_transferred: int | None
    fetched_at: datetime | None
    response_time_ms: int | None
    occurrence_count: int
    source_page_count: int
    anchor_occurrence_count: int
    embedded_occurrence_count: int
    in_scope_occurrence_count: int
    out_of_scope_occurrence_count: int
    first_discovered_at: datetime | None
    latest_discovered_at: datetime | None
    observation_count: int = 0
    scan_count: int = 0


class ResourceInventoryList(BaseModel):
    items: list[ResourceInventoryItem]
    total: int
    limit: int
    offset: int


class ResourceSummary(BaseModel):
    unique_resources: int
    observed_resources: int
    discovered_only_resources: int
    total_occurrences: int
    kind_counts: dict[str, int] = Field(default_factory=dict)


class ResourceOccurrenceRead(BaseModel):
    occurrence_id: int
    occurrence_source: str
    source_snapshot_id: int
    source_resource_id: int
    source_url: str
    source_title: str | None
    relation_type: str
    element_tag: str | None
    attribute_name: str | None
    raw_url: str | None
    resolved_url: str | None
    anchor_text: str | None
    alt_text: str | None
    srcset_descriptor: str | None
    rel: str | None
    media: str | None
    type_hint: str | None
    as_hint: str | None
    scope_decision: str
    in_scope: bool
    dom_path: str | None
    discovered_at: datetime


class ResourceOccurrenceList(BaseModel):
    items: list[ResourceOccurrenceRead]
    total: int
    limit: int
    offset: int


class ResourceDetail(BaseModel):
    resource: ResourceInventoryItem
    requested_url: str | None = None
    response_body_state: str | None = None
    inspected_prefix_byte_count: int = 0


class ResourceHistoryItem(BaseModel):
    resource_id: int
    scan_id: int
    scan_created_at: datetime
    scan_status: str
    observed: bool
    discovered_only: bool
    effective_kind: str
    normalized_mime_type: str | None
    http_status: int | None
    declared_content_length: int | None
    occurrence_count: int
    observed_at: datetime | None
    snapshot_id: int | None


class ResourceHistoryList(BaseModel):
    items: list[ResourceHistoryItem]
    total: int
    limit: int
    offset: int
