from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AiDocumentSettings(BaseModel):
    max_nesting_depth: int = Field(5, ge=0, le=10)
    max_index_documents: int = Field(100, ge=1, le=1000)
    max_total_documents: int = Field(1000, ge=1, le=5000)
    max_references_per_document: int = Field(10000, ge=1, le=10000)
    max_individual_document_bytes: int = Field(5_000_000, ge=1024, le=20_000_000)
    max_total_retained_bytes: int = Field(100_000_000, ge=1024, le=500_000_000)
    max_total_network_bytes: int = Field(250_000_000, ge=1024, le=1_000_000_000)
    follow_external_documents: bool = False
    save_declared_documents: bool = True

    @model_validator(mode="after")
    def validate_totals(self) -> "AiDocumentSettings":
        if self.max_total_retained_bytes < self.max_individual_document_bytes:
            raise ValueError("Total retained bytes must allow at least one individual document.")
        return self


class AiDocumentSourceCreate(BaseModel):
    entry_url: str
    name: str = Field(min_length=1, max_length=255)
    discovery_mode: str = Field("configured", max_length=64)
    is_active: bool = True
    settings: AiDocumentSettings = Field(default_factory=AiDocumentSettings)


class AiDocumentDiscoveryCandidate(BaseModel):
    url: str
    discovery_method: str
    relation: str | None = None
    status: Literal["found", "not_found", "blocked", "error"]
    http_status: int | None = None
    message: str | None = None
    already_configured: bool = False


class AiDocumentDiscoveryResult(BaseModel):
    candidates: list[AiDocumentDiscoveryCandidate]


class AiDocumentSourceRead(BaseModel):
    id: int
    website_property_id: int
    site_name: str
    name: str
    entry_url: str
    discovery_mode: str
    is_active: bool
    settings: AiDocumentSettings
    last_refresh_status: str | None
    last_successful_refresh_at: datetime | None
    current_entry_count: int = 0
    latest_refresh_id: int | None = None
    document_count: int = 0
    reference_count: int = 0
    warning_count: int = 0
    retained_bytes: int = 0


class AiDocumentRefreshRead(BaseModel):
    id: int
    source_refresh_id: int
    status: str
    configuration_json: dict[str, Any]
    root_candidate_count: int
    document_discovered_count: int
    document_fetched_count: int
    document_saved_count: int
    document_unchanged_count: int
    document_changed_count: int
    document_failed_count: int
    document_skipped_count: int
    reference_count: int
    cycle_count: int
    total_network_bytes: int
    total_retained_bytes: int
    stop_reason: str | None
    fatal_error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AiDocumentSnapshotRead(BaseModel):
    id: int
    refresh_id: int
    resource_id: int
    requested_url: str
    final_url: str | None
    parent_depth_min: int
    document_role: str
    document_kind: str
    classification_rule: str
    fetch_state: str
    http_status: int | None
    normalized_mime_type: str | None
    encoding: str | None
    response_headers: dict[str, str]
    redirect_chain: list[dict[str, Any]]
    fetched_at: datetime | None
    response_time_ms: int | None
    network_bytes_transferred: int
    raw_sha256: str | None
    parsed_title: str | None
    parsed_summary: str | None
    parse_state: str
    parse_version: str | None
    parse_warnings_json: list[dict[str, Any]]
    warning_count: int
    change_state: str
    error_type: str | None
    error_message: str | None
    raw_byte_size: int | None = None
    stored_byte_size: int | None = None
    parent_count: int = 0

    model_config = {"from_attributes": True}


class AiDocumentReferenceRead(BaseModel):
    id: int
    parent_snapshot_id: int
    target_resource_id: int | None
    child_snapshot_id: int | None
    position: int
    section_title: str | None
    label: str | None
    description: str | None
    raw_url: str
    resolved_url: str | None
    normalized_target_url: str | None
    optional: bool
    inferred_role: str
    inferred_kind: str
    classification_rule: str
    in_scope: bool
    scope_decision: str
    exclusion_reason: str | None
    discovery_depth: int
    forms_cycle: bool
    inventory_entry_id: int | None

    model_config = {"from_attributes": True}


class AiValidationRead(BaseModel):
    id: int
    snapshot_id: int | None
    reference_id: int | None
    severity: str
    code: str
    message: str
    data_json: dict[str, Any]

    model_config = {"from_attributes": True}


class PaginatedAiDocuments(BaseModel):
    items: list[AiDocumentSnapshotRead]
    total: int
    limit: int
    offset: int


class PaginatedAiReferences(BaseModel):
    items: list[AiDocumentReferenceRead]
    total: int
    limit: int
    offset: int


class PaginatedAiRefreshes(BaseModel):
    items: list[AiDocumentRefreshRead]
    total: int
    limit: int
    offset: int


class AiDocumentTreeNode(BaseModel):
    snapshot: AiDocumentSnapshotRead
    parent_count: int
    cycle: bool


class AiDocumentTree(BaseModel):
    items: list[AiDocumentTreeNode]


class AiSourceDeletePreview(BaseModel):
    refresh_count: int
    snapshot_count: int
    reference_count: int
    current_inventory_origin_count: int
    unique_blob_count: int
    shared_blob_count: int
    exclusive_blob_count: int
    reclaimable_storage_bytes: int
