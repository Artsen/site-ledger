from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("website_properties.id"), index=True
    )
    starting_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    scope_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    conditional_request_count: Mapped[int] = mapped_column(Integer, default=0)
    not_modified_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_reuse_count: Mapped[int] = mapped_column(Integer, default=0)
    full_parse_count: Mapped[int] = mapped_column(Integer, default=0)
    network_bytes_transferred: Mapped[int] = mapped_column(Integer, default=0)
    reused_content_bytes: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(128))
    fatal_error_message: Mapped[str | None] = mapped_column(Text)

    snapshots: Mapped[list["ResourceSnapshot"]] = relationship(back_populates="scan")
    website_property: Mapped["WebsiteProperty | None"] = relationship(back_populates="scans")
    seeds: Mapped[list["ScanSeed"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["BackgroundJob"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(back_populates="scan", cascade="all, delete-orphan")

    @property
    def website_property_name(self) -> str | None:
        return self.website_property.name if self.website_property else None

    @property
    def website_property_base_url(self) -> str | None:
        return self.website_property.base_url if self.website_property else None


class WebsiteProperty(Base):
    __tablename__ = "website_properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(Text)
    normalized_base_url: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    group_key: Mapped[str] = mapped_column(String(64), index=True)
    locale: Mapped[str | None] = mapped_column(String(32), index=True)
    platform_key: Mapped[str] = mapped_column(String(64), index=True)
    ownership_key: Mapped[str] = mapped_column(String(64), index=True)
    scope_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    scans: Mapped[list[Scan]] = relationship(back_populates="website_property")
    url_sources: Mapped[list["UrlSource"]] = relationship(
        back_populates="website_property", cascade="all, delete-orphan"
    )
    site_pages: Mapped[list["SitePage"]] = relationship(
        back_populates="website_property", cascade="all, delete-orphan"
    )
    page_categories: Mapped[list["PageCategory"]] = relationship(
        back_populates="website_property", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(
        back_populates="website_property", cascade="all, delete-orphan"
    )


class WebResource(Base):
    __tablename__ = "web_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(32), default="page")
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    scheme: Mapped[str] = mapped_column(String(16), index=True)
    host: Mapped[str] = mapped_column(String(255), index=True)
    port: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    snapshots: Mapped[list["ResourceSnapshot"]] = relationship(back_populates="resource")
    source_entries: Mapped[list["UrlSourceEntry"]] = relationship(back_populates="resource")
    scan_seeds: Mapped[list["ScanSeed"]] = relationship(back_populates="resource")
    site_pages: Mapped[list["SitePage"]] = relationship(back_populates="resource")

    __table_args__ = (
        UniqueConstraint("resource_type", "normalized_url", name="uq_resource_type_url"),
    )


class ContentBlob(Base):
    __tablename__ = "content_blobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    compression_type: Mapped[str] = mapped_column(String(32), default="gzip")
    content_type: Mapped[str | None] = mapped_column(Text)
    encoding: Mapped[str | None] = mapped_column(String(64))
    raw_byte_size: Mapped[int] = mapped_column(Integer)
    stored_byte_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parse_artifacts: Mapped[list["HtmlParseArtifact"]] = relationship(back_populates="content_blob")


class HtmlParseArtifact(Base):
    __tablename__ = "html_parse_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_blob_id: Mapped[int] = mapped_column(
        ForeignKey("content_blobs.id", ondelete="CASCADE"), index=True
    )
    parser_version: Mapped[str] = mapped_column(String(64))
    parser_config_version: Mapped[str] = mapped_column(String(64))
    resolution_base_url: Mapped[str] = mapped_column(Text)
    page_title: Mapped[str | None] = mapped_column(Text)
    html_language: Mapped[str | None] = mapped_column(String(64))
    meta_description: Mapped[str | None] = mapped_column(Text)
    meta_robots: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    document_encoding: Mapped[str | None] = mapped_column(String(64))
    viewport: Mapped[str | None] = mapped_column(Text)
    head_sha256: Mapped[str] = mapped_column(String(64), index=True)
    parsed_head_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    anchor_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    content_blob: Mapped[ContentBlob] = relationship(back_populates="parse_artifacts")
    anchors: Mapped[list["HtmlParseAnchor"]] = relationship(
        back_populates="parse_artifact", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["ResourceSnapshot"]] = relationship(back_populates="parse_artifact")

    __table_args__ = (
        UniqueConstraint(
            "content_blob_id",
            "parser_version",
            "parser_config_version",
            "resolution_base_url",
            name="uq_html_parse_artifact_identity",
        ),
    )


class HtmlParseAnchor(Base):
    __tablename__ = "html_parse_anchors"

    id: Mapped[int] = mapped_column(primary_key=True)
    parse_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("html_parse_artifacts.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    raw_href: Mapped[str | None] = mapped_column(Text)
    resolved_url: Mapped[str | None] = mapped_column(Text)
    anchor_text: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    aria_label: Mapped[str | None] = mapped_column(Text)
    rel: Mapped[str | None] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(String(128))
    dom_path: Mapped[str | None] = mapped_column(Text)
    link_role: Mapped[str | None] = mapped_column(String(32))
    link_role_rule: Mapped[str | None] = mapped_column(String(64))
    link_context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    parse_artifact: Mapped[HtmlParseArtifact] = relationship(back_populates="anchors")

    __table_args__ = (
        UniqueConstraint("parse_artifact_id", "position", name="uq_parse_anchor_position"),
        Index("ix_parse_anchor_artifact_position", "parse_artifact_id", "position"),
    )


class ResourceSnapshot(Base):
    __tablename__ = "resource_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer, index=True)
    content_type: Mapped[str | None] = mapped_column(Text)
    encoding: Mapped[str | None] = mapped_column(String(64))
    crawl_depth: Mapped[int] = mapped_column(Integer, index=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    redirect_chain: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    html_blob_id: Mapped[int | None] = mapped_column(ForeignKey("content_blobs.id"))
    parse_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("html_parse_artifacts.id", ondelete="SET NULL"), index=True
    )
    reused_from_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL"), index=True
    )
    raw_html_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    head_sha256: Mapped[str | None] = mapped_column(String(64))
    page_title: Mapped[str | None] = mapped_column(Text)
    html_language: Mapped[str | None] = mapped_column(String(64))
    meta_description: Mapped[str | None] = mapped_column(Text)
    meta_robots: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    parsed_head_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fetch_state: Mapped[str] = mapped_column(String(32), index=True)
    error_type: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    retrieval_method: Mapped[str | None] = mapped_column(String(64), index=True)
    parse_method: Mapped[str | None] = mapped_column(String(64), index=True)
    retrieval_http_status: Mapped[int | None] = mapped_column(Integer, index=True)
    retrieval_response_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    network_bytes_transferred: Mapped[int | None] = mapped_column(Integer)
    request_variant_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    cache_control: Mapped[str | None] = mapped_column(Text)
    vary_header: Mapped[str | None] = mapped_column(Text)

    scan: Mapped[Scan] = relationship(back_populates="snapshots")
    resource: Mapped[WebResource] = relationship(back_populates="snapshots")
    blob: Mapped[ContentBlob | None] = relationship()
    parse_artifact: Mapped[HtmlParseArtifact | None] = relationship(
        back_populates="snapshots", foreign_keys=[parse_artifact_id]
    )
    reused_from_snapshot: Mapped["ResourceSnapshot | None"] = relationship(
        remote_side=[id], foreign_keys=[reused_from_snapshot_id]
    )
    occurrences: Mapped[list["ResourceOccurrence"]] = relationship(back_populates="source_snapshot")

    __table_args__ = (
        Index("ix_snapshot_scan_resource", "scan_id", "resource_id"),
        Index("ix_snapshot_resource_fetched", "resource_id", "fetched_at", "id"),
    )


class ResourceOccurrence(Base):
    __tablename__ = "resource_occurrences"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), default="page_link", index=True)
    raw_href: Mapped[str | None] = mapped_column(Text)
    resolved_url: Mapped[str | None] = mapped_column(Text)
    normalized_target_url: Mapped[str | None] = mapped_column(Text, index=True)
    target_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("web_resources.id"), index=True
    )
    anchor_text: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    aria_label: Mapped[str | None] = mapped_column(Text)
    rel: Mapped[str | None] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(String(128))
    dom_path: Mapped[str | None] = mapped_column(Text)
    in_scope: Mapped[bool] = mapped_column(default=False)
    scope_decision: Mapped[str] = mapped_column(String(64), index=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    link_role: Mapped[str | None] = mapped_column(String(32))
    link_role_rule: Mapped[str | None] = mapped_column(String(64))
    link_context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source_snapshot: Mapped[ResourceSnapshot] = relationship(back_populates="occurrences")
    target_resource: Mapped[WebResource | None] = relationship()

    __table_args__ = (
        Index("ix_occurrence_source_target", "source_snapshot_id", "target_resource_id"),
        Index("ix_occurrence_source_role", "source_snapshot_id", "link_role"),
        Index("ix_occurrence_target_role", "target_resource_id", "link_role"),
    )

    @property
    def link_role_label(self) -> str:
        if self.link_role is None:
            return "Unclassified legacy link"
        from app.crawler.link_roles import LINK_ROLE_LABELS

        return LINK_ROLE_LABELS.get(self.link_role, "Unknown")


class SitePage(Base):
    __tablename__ = "site_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    owner_label: Mapped[str | None] = mapped_column(String(128))
    workflow_status: Mapped[str] = mapped_column(String(32), default="unreviewed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    website_property: Mapped[WebsiteProperty] = relationship(back_populates="site_pages")
    resource: Mapped[WebResource] = relationship(back_populates="site_pages")
    category_assignments: Mapped[list["PageCategoryAssignment"]] = relationship(
        back_populates="site_page", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(
        back_populates="site_page", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("website_property_id", "resource_id", name="uq_site_page_resource"),
        Index("ix_site_page_site_workflow", "website_property_id", "workflow_status"),
    )


class PageCategory(Base):
    __tablename__ = "page_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    color_key: Mapped[str] = mapped_column(String(16), default="stone")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    website_property: Mapped[WebsiteProperty] = relationship(back_populates="page_categories")
    assignments: Mapped[list["PageCategoryAssignment"]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "website_property_id", "normalized_name", name="uq_site_category_normalized_name"
        ),
        Index("ix_page_category_site_active", "website_property_id", "is_active"),
    )


class PageCategoryAssignment(Base):
    __tablename__ = "page_category_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_page_id: Mapped[int] = mapped_column(
        ForeignKey("site_pages.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("page_categories.id", ondelete="CASCADE"), index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    site_page: Mapped[SitePage] = relationship(back_populates="category_assignments")
    category: Mapped[PageCategory] = relationship(back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("site_page_id", "category_id", name="uq_site_page_category"),
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE")
    )
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    site_page_id: Mapped[int | None] = mapped_column(
        ForeignKey("site_pages.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(Text)
    is_pinned: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    website_property: Mapped[WebsiteProperty | None] = relationship(back_populates="notes")
    scan: Mapped[Scan | None] = relationship(back_populates="notes")
    site_page: Mapped[SitePage | None] = relationship(back_populates="notes")

    __table_args__ = (
        CheckConstraint(
            "(website_property_id IS NOT NULL AND scan_id IS NULL AND site_page_id IS NULL) OR "
            "(website_property_id IS NULL AND scan_id IS NOT NULL AND site_page_id IS NULL) OR "
            "(website_property_id IS NULL AND scan_id IS NULL AND site_page_id IS NOT NULL)",
            name="ck_note_exactly_one_target",
        ),
        Index("ix_note_site_updated", "website_property_id", "updated_at"),
        Index("ix_note_scan_updated", "scan_id", "updated_at"),
        Index("ix_note_site_page_updated", "site_page_id", "updated_at"),
    )


class UrlSource(Base):
    __tablename__ = "url_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    parent_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("url_sources.id", ondelete="CASCADE"), index=True
    )
    root_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("url_sources.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    normalized_source_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    discovery_mode: Mapped[str] = mapped_column(String(64), index=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_refresh_status: Mapped[str | None] = mapped_column(String(32), index=True)
    last_refresh_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_error_type: Mapped[str | None] = mapped_column(String(64), index=True)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    website_property: Mapped[WebsiteProperty] = relationship(back_populates="url_sources")
    parent_source: Mapped["UrlSource | None"] = relationship(
        remote_side=[id], foreign_keys=[parent_source_id], post_update=True
    )
    root_source: Mapped["UrlSource | None"] = relationship(
        remote_side=[id], foreign_keys=[root_source_id], post_update=True
    )
    entries: Mapped[list["UrlSourceEntry"]] = relationship(
        back_populates="url_source", cascade="all, delete-orphan"
    )
    refreshes: Mapped[list["SourceRefresh"]] = relationship(
        back_populates="url_source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "website_property_id",
            "source_type",
            "normalized_source_url",
            name="uq_site_source_type_url",
        ),
    )


class SourceRefresh(Base):
    __tablename__ = "source_refreshes"

    id: Mapped[int] = mapped_column(primary_key=True)
    url_source_id: Mapped[int] = mapped_column(
        ForeignKey("url_sources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetched_url: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    response_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str | None] = mapped_column(Text)
    discovered_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    child_source_count: Mapped[int] = mapped_column(Integer, default=0)
    entries_added: Mapped[int] = mapped_column(Integer, default=0)
    entries_updated: Mapped[int] = mapped_column(Integer, default=0)
    entries_no_longer_current: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    url_source: Mapped[UrlSource] = relationship(back_populates="refreshes")
    jobs: Mapped[list["BackgroundJob"]] = relationship(
        back_populates="source_refresh", cascade="all, delete-orphan"
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True
    )
    source_refresh_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_refreshes.id", ondelete="CASCADE"), index=True
    )
    website_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("website_properties.id", ondelete="SET NULL"), index=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress_version: Mapped[int] = mapped_column(Integer, default=1)
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_operation: Mapped[str | None] = mapped_column(Text)
    progress_current: Mapped[int | None] = mapped_column(Integer)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    progress_unit: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(128))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scan: Mapped[Scan | None] = relationship(back_populates="jobs")
    source_refresh: Mapped[SourceRefresh | None] = relationship(back_populates="jobs")
    website_property: Mapped[WebsiteProperty | None] = relationship()
    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL)",
            name="ck_background_job_one_subject",
        ),
        Index(
            "ix_background_jobs_claim",
            "status",
            "priority",
            "available_at",
            "created_at",
            "id",
        ),
        Index("ix_background_jobs_type_status", "job_type", "status"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    message: Mapped[str] = mapped_column(Text)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped[BackgroundJob] = relationship(back_populates="events")

    __table_args__ = (Index("ix_job_events_job_created", "job_id", "created_at", "id"),)


class WorkerInstance(Base):
    __tablename__ = "worker_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(128), unique=True)
    hostname: Mapped[str | None] = mapped_column(String(255))
    process_id: Mapped[int | None] = mapped_column(Integer)
    application_version: Mapped[str | None] = mapped_column(String(64))
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="online", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class UrlSourceEntry(Base):
    __tablename__ = "url_source_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    url_source_id: Mapped[int] = mapped_column(
        ForeignKey("url_sources.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("web_resources.id"), index=True)
    normalized_url: Mapped[str | None] = mapped_column(Text, index=True)
    raw_url: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_refresh_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_refreshes.id", ondelete="SET NULL"), index=True
    )
    is_current: Mapped[bool] = mapped_column(default=True, index=True)
    sitemap_lastmod: Mapped[str | None] = mapped_column(Text)
    sitemap_changefreq: Mapped[str | None] = mapped_column(String(32))
    sitemap_priority: Mapped[str | None] = mapped_column(String(32))
    source_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_state: Mapped[str] = mapped_column(String(32), index=True)
    validation_message: Mapped[str | None] = mapped_column(Text)
    scope_decision: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    url_source: Mapped[UrlSource] = relationship(back_populates="entries")
    resource: Mapped[WebResource | None] = relationship(back_populates="source_entries")

    __table_args__ = (
        UniqueConstraint("url_source_id", "normalized_url", name="uq_source_normalized_entry"),
        Index("ix_source_entry_source_current", "url_source_id", "is_current"),
    )


class ScanSeed(Base):
    __tablename__ = "scan_seeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("web_resources.id"), index=True)
    normalized_url: Mapped[str | None] = mapped_column(Text, index=True)
    requested_url: Mapped[str] = mapped_column(Text)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    queue_state: Mapped[str] = mapped_column(String(32), index=True)
    scope_decision: Mapped[str] = mapped_column(String(64), index=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resource: Mapped[WebResource | None] = relationship(back_populates="scan_seeds")
    scan: Mapped[Scan] = relationship(back_populates="seeds")
    origins: Mapped[list["ScanSeedOrigin"]] = relationship(
        back_populates="scan_seed", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("scan_id", "normalized_url", name="uq_scan_seed_url"),)


class ScanSeedOrigin(Base):
    __tablename__ = "scan_seed_origins"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_seed_id: Mapped[int] = mapped_column(
        ForeignKey("scan_seeds.id", ondelete="CASCADE"), index=True
    )
    origin_type: Mapped[str] = mapped_column(String(32), index=True)
    url_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("url_sources.id", ondelete="SET NULL")
    )
    url_source_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("url_source_entries.id", ondelete="SET NULL")
    )
    source_refresh_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_refreshes.id", ondelete="SET NULL")
    )
    raw_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    scan_seed: Mapped[ScanSeed] = relationship(back_populates="origins")
    url_source: Mapped[UrlSource | None] = relationship()
    url_source_entry: Mapped[UrlSourceEntry | None] = relationship()
    source_refresh: Mapped[SourceRefresh | None] = relationship()
