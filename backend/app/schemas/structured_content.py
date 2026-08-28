from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class StructuredContentProvenance(BaseModel):
    snapshot_id: int
    scan_id: int
    site_id: int | None
    content_blob_id: int
    raw_html_sha256: str | None
    requested_url: str
    final_url: str | None
    fetched_at: datetime | None
    retrieval_method: str | None
    reused_from_snapshot_id: int | None


class StructuredContentArtifactRead(BaseModel):
    id: int
    extractor_version: str
    extractor_config_version: str
    extraction_state: str
    document_profile: str
    section_count: int
    heading_count: int
    heading_counts: dict[str, int]
    document_word_count: int
    document_character_count: int
    document_text_sha256: str
    outline_sha256: str
    is_truncated: bool
    truncation_reasons: list[str]
    node_count: int
    canonical_document_sha256: str | None
    markdown_renderer_version: str | None
    markdown_sha256: str | None
    markdown_character_count: int | None
    created_at: datetime


class StructuredContentSectionRead(BaseModel):
    id: int
    position: int
    parent_section_id: int | None
    kind: str
    heading_level: int | None
    heading_text: str | None
    heading_dom_path: str | None
    region_key: str
    region_dom_path: str | None
    direct_text: str
    direct_text_sha256: str
    section_sha256: str
    subtree_sha256: str
    direct_word_count: int
    direct_character_count: int
    subtree_word_count: int
    subtree_character_count: int
    child_count: int
    descendant_count: int
    block_count: int
    has_direct_content: bool


class StructuredContentRead(BaseModel):
    status: Literal["ready", "partial", "unavailable", "not_prepared", "not_applicable"]
    reason: str | None = None
    provenance: StructuredContentProvenance | None = None
    artifact: StructuredContentArtifactRead | None = None
    items: list[StructuredContentSectionRead]
    total: int
    limit: int
    offset: int


class StructuredContentNodeRead(BaseModel):
    id: int
    position: int
    parent_node_id: int | None
    kind: str
    depth: int
    source_tag: str | None
    source_dom_path: str | None
    region_key: str
    region_dom_path: str | None
    text: str | None
    inline: list[dict[str, object]]
    source_attributes: dict[str, str]
    semantic: dict[str, object]
    semantic_sha256: str
    subtree_sha256: str
    child_count: int
    descendant_count: int


class StructuredContentDocumentRead(BaseModel):
    status: Literal["ready", "partial", "unavailable", "not_prepared", "not_applicable"]
    reason: str | None = None
    provenance: StructuredContentProvenance | None = None
    artifact: StructuredContentArtifactRead | None = None
    items: list[StructuredContentNodeRead]
    total: int
    limit: int
    offset: int
