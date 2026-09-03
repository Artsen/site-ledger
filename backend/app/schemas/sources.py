from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceType = Literal["sitemap", "robots", "manual"]
DiscoveryMode = Literal[
    "configured", "robots_discovered", "sitemap_index_discovered", "system_manual_collection"
]


class UrlSourceCreate(BaseModel):
    source_type: SourceType = "sitemap"
    name: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    is_active: bool = True
    discovery_mode: DiscoveryMode = "configured"
    settings_json: dict[str, Any] = Field(default_factory=dict)


class UrlSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    is_active: bool | None = None
    settings_json: dict[str, Any] | None = None


class UrlSourceRead(BaseModel):
    id: int
    website_property_id: int
    parent_source_id: int | None
    root_source_id: int | None
    source_type: str
    name: str
    source_url: str | None
    normalized_source_url: str | None
    is_active: bool
    discovery_mode: str
    settings_json: dict[str, Any]
    last_refresh_status: str | None
    last_refresh_started_at: datetime | None
    last_refresh_finished_at: datetime | None
    last_successful_refresh_at: datetime | None
    last_http_status: int | None
    last_error_type: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    current_entry_count: int = 0

    model_config = {"from_attributes": True}


class UrlSourceList(BaseModel):
    items: list[UrlSourceRead]
    total: int
    limit: int
    offset: int


class SourceRefreshRead(BaseModel):
    id: int
    url_source_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    http_status: int | None
    fetched_url: str | None
    final_url: str | None
    response_bytes: int
    content_type: str | None
    discovered_entry_count: int
    accepted_entry_count: int
    rejected_entry_count: int
    child_source_count: int
    membership_materialized: bool
    entries_added: int
    entries_updated: int
    entries_no_longer_current: int
    error_type: str | None
    error_message: str | None
    warnings_json: list[dict[str, Any]]

    model_config = {"from_attributes": True}


class BulkSourceRefreshCreate(BaseModel):
    source_ids: list[int] = Field(min_length=1, max_length=100)


class UrlSourceEntryRead(BaseModel):
    id: int
    url_source_id: int
    resource_id: int | None
    normalized_url: str | None
    raw_url: str
    first_seen_at: datetime
    last_seen_at: datetime
    last_refresh_id: int | None
    is_current: bool
    sitemap_lastmod: str | None
    sitemap_changefreq: str | None
    sitemap_priority: str | None
    source_metadata_json: dict[str, Any]
    validation_state: str
    validation_message: str | None
    scope_decision: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UrlSourceEntryList(BaseModel):
    items: list[UrlSourceEntryRead]
    total: int
    limit: int
    offset: int


class ManualUrlBatchCreate(BaseModel):
    urls_text: str = Field(min_length=1, max_length=100_000)


class ManualUrlBatchResult(BaseModel):
    source: UrlSourceRead
    items: list[UrlSourceEntryRead]
    accepted_count: int
    rejected_count: int
    duplicate_count: int


class InventoryItem(BaseModel):
    normalized_url: str | None
    resource_id: int | None
    source_count: int
    source_types: list[str]
    sources: list[dict[str, Any]]
    scope_decision: str
    validation_state: str
    sitemap_lastmod: str | None
    latest_scan_status: str | None = None
    latest_fetch_date: datetime | None = None
    classification: str
    suppression_id: int | None = None
    is_suppressed: bool = False
    suppressed_at: datetime | None = None


class InventorySuppressionCreate(BaseModel):
    entry_id: int = Field(gt=0)


class BulkInventorySuppressionCreate(BaseModel):
    entry_ids: list[int] = Field(min_length=1, max_length=500)


class BulkInventoryEntryDelete(BaseModel):
    entry_ids: list[int] = Field(min_length=1, max_length=500)


class BulkInventorySuppressionRestore(BaseModel):
    suppression_ids: list[int] = Field(min_length=1, max_length=500)


class InventorySuppressionRead(BaseModel):
    id: int
    website_property_id: int
    target_kind: Literal["normalized_url", "raw_url"]
    target_value: str
    normalization_version: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InventoryList(BaseModel):
    items: list[InventoryItem]
    total: int
    limit: int
    offset: int


class ScanSeedOriginRead(BaseModel):
    id: int
    origin_type: str
    url_source_id: int | None
    url_source_entry_id: int | None
    source_refresh_id: int | None
    raw_url: str | None
    metadata_json: dict[str, Any]

    model_config = {"from_attributes": True}


class ScanSeedRead(BaseModel):
    id: int
    scan_id: int
    resource_id: int | None
    normalized_url: str | None
    requested_url: str
    depth: int
    queue_state: str
    scope_decision: str
    exclusion_reason: str | None
    created_at: datetime
    origins: list[ScanSeedOriginRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ScanSeedList(BaseModel):
    items: list[ScanSeedRead]
    total: int
    limit: int
    offset: int
