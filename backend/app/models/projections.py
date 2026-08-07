from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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


class ScanProjectionState(Base):
    __tablename__ = "scan_projection_states"

    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), primary_key=True
    )
    current_build_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_projection_builds.id", ondelete="SET NULL"), unique=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    current_build: Mapped[ScanProjectionBuild | None] = relationship(
        foreign_keys=[current_build_id], post_update=True
    )


class ScanProjectionBuild(Base):
    __tablename__ = "scan_projection_builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    projection_version: Mapped[str] = mapped_column(String(64), index=True)
    algorithm_identity: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    active_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    resource_count: Mapped[int] = mapped_column(Integer, default=0)
    link_edge_count: Mapped[int] = mapped_column(Integer, default=0)
    graph_node_count: Mapped[int] = mapped_column(Integer, default=0)
    graph_edge_count: Mapped[int] = mapped_column(Integer, default=0)
    rendered_page_count: Mapped[int] = mapped_column(Integer, default=0)
    source_snapshot_count: Mapped[int] = mapped_column(Integer, default=0)
    source_link_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    source_resource_reference_count: Mapped[int] = mapped_column(Integer, default=0)
    build_duration_ms: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pages: Mapped[list[ScanPageProjection]] = relationship(
        back_populates="build", cascade="all, delete-orphan"
    )
    resources: Mapped[list[ScanResourceProjection]] = relationship(
        back_populates="build", cascade="all, delete-orphan"
    )
    links: Mapped[list[ScanLinkProjection]] = relationship(
        back_populates="build", cascade="all, delete-orphan"
    )
    summary: Mapped[ScanSummaryProjection | None] = relationship(
        back_populates="build", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        Index("ix_projection_build_scan_version_status", "scan_id", "projection_version", "status"),
    )


class ScanPageProjection(Base):
    __tablename__ = "scan_page_projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    projection_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_projection_builds.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("resource_snapshots.id"))
    resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"))
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    page_title: Mapped[str | None] = mapped_column(Text)
    crawl_depth: Mapped[int] = mapped_column(Integer)
    fetch_state: Mapped[str] = mapped_column(String(32))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    head_hash: Mapped[str | None] = mapped_column(String(64))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    robots_directives: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(64))
    redirects: Mapped[bool] = mapped_column(default=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    network_bytes_transferred: Mapped[int | None] = mapped_column(Integer)
    raw_html_size: Mapped[int | None] = mapped_column(Integer)
    stored_html_size: Mapped[int | None] = mapped_column(Integer)
    inbound_source_page_count: Mapped[int] = mapped_column(Integer, default=0)
    inbound_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    outbound_target_count: Mapped[int] = mapped_column(Integer, default=0)
    outbound_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    embedded_resource_count: Mapped[int] = mapped_column(Integer, default=0)
    discovery_source: Mapped[str | None] = mapped_column(Text)
    is_seed: Mapped[bool] = mapped_column(default=False)
    seed_origin_count: Mapped[int] = mapped_column(Integer, default=0)
    is_starting_page: Mapped[bool] = mapped_column(default=False)
    rendered_capture_state: Mapped[str | None] = mapped_column(String(32))
    rendered_network_count: Mapped[int] = mapped_column(Integer, default=0)
    rendered_console_count: Mapped[int] = mapped_column(Integer, default=0)
    rendered_page_error_count: Mapped[int] = mapped_column(Integer, default=0)
    rendered_artifact_count: Mapped[int] = mapped_column(Integer, default=0)
    rendered_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    build: Mapped[ScanProjectionBuild] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint("projection_build_id", "snapshot_id", name="uq_projection_page_snapshot"),
        Index("ix_projection_page_build_url", "projection_build_id", "normalized_url"),
        Index("ix_projection_page_build_status", "projection_build_id", "http_status"),
        Index("ix_projection_page_build_fetch", "projection_build_id", "fetch_state"),
        Index("ix_projection_page_build_depth", "projection_build_id", "crawl_depth"),
        Index("ix_projection_page_build_resource", "projection_build_id", "resource_id"),
        Index("ix_projection_page_build_snapshot", "projection_build_id", "snapshot_id"),
        Index("ix_projection_page_build_fetched", "projection_build_id", "fetched_at"),
    )


class ScanResourceProjection(Base):
    __tablename__ = "scan_resource_projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    projection_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_projection_builds.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"))
    normalized_url: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    file_extension: Mapped[str | None] = mapped_column(String(32))
    effective_kind: Mapped[str] = mapped_column(String(32))
    classification_source: Mapped[str] = mapped_column(String(64))
    observed: Mapped[bool] = mapped_column(default=False)
    discovered_only: Mapped[bool] = mapped_column(default=False)
    latest_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("resource_snapshots.id"))
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    normalized_mime_type: Mapped[str | None] = mapped_column(String(255))
    content_disposition_filename: Mapped[str | None] = mapped_column(String(255))
    declared_content_length: Mapped[int | None] = mapped_column(Integer)
    network_bytes_transferred: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    source_page_count: Mapped[int] = mapped_column(Integer, default=0)
    anchor_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    embedded_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    in_scope_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    out_of_scope_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    first_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_count: Mapped[int] = mapped_column(Integer, default=0)

    build: Mapped[ScanProjectionBuild] = relationship(back_populates="resources")

    __table_args__ = (
        UniqueConstraint("projection_build_id", "resource_id", name="uq_projection_resource"),
        Index("ix_projection_resource_build_url", "projection_build_id", "normalized_url"),
        Index("ix_projection_resource_build_kind", "projection_build_id", "effective_kind"),
        Index("ix_projection_resource_build_observed", "projection_build_id", "observed"),
        Index("ix_projection_resource_build_mime", "projection_build_id", "normalized_mime_type"),
        Index("ix_projection_resource_build_extension", "projection_build_id", "file_extension"),
        Index("ix_projection_resource_build_host", "projection_build_id", "host"),
        Index("ix_projection_resource_build_status", "projection_build_id", "http_status"),
        Index(
            "ix_projection_resource_build_occurrences", "projection_build_id", "occurrence_count"
        ),
        Index("ix_projection_resource_build_sources", "projection_build_id", "source_page_count"),
        Index("ix_projection_resource_build_latest", "projection_build_id", "latest_discovered_at"),
    )


class ScanLinkProjection(Base):
    __tablename__ = "scan_link_projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    projection_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_projection_builds.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("resource_snapshots.id"))
    source_resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"))
    target_resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"))
    target_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("resource_snapshots.id"))
    occurrence_count: Mapped[int] = mapped_column(Integer)
    unique_anchor_count: Mapped[int] = mapped_column(Integer)
    empty_anchor_count: Mapped[int] = mapped_column(Integer)
    follow_count: Mapped[int] = mapped_column(Integer)
    nofollow_count: Mapped[int] = mapped_column(Integer)
    self_link: Mapped[bool] = mapped_column(default=False)
    in_scope_count: Mapped[int] = mapped_column(Integer, default=0)
    out_of_scope_count: Mapped[int] = mapped_column(Integer, default=0)
    role_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    scope_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    dom_regions_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    sample_anchors_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    first_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    build: Mapped[ScanProjectionBuild] = relationship(back_populates="links")

    __table_args__ = (
        UniqueConstraint(
            "projection_build_id",
            "source_snapshot_id",
            "target_resource_id",
            name="uq_projection_link_edge",
        ),
        Index("ix_projection_link_build_source", "projection_build_id", "source_snapshot_id"),
        Index("ix_projection_link_build_target", "projection_build_id", "target_resource_id"),
        Index(
            "ix_projection_link_build_target_snapshot", "projection_build_id", "target_snapshot_id"
        ),
        Index("ix_projection_link_build_occurrences", "projection_build_id", "occurrence_count"),
    )


class ScanSummaryProjection(Base):
    __tablename__ = "scan_summary_projections"

    id: Mapped[int] = mapped_column(primary_key=True)
    projection_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_projection_builds.id", ondelete="CASCADE"), unique=True
    )
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    page_total: Mapped[int] = mapped_column(Integer, default=0)
    successful_page_total: Mapped[int] = mapped_column(Integer, default=0)
    failed_page_total: Mapped[int] = mapped_column(Integer, default=0)
    resource_total: Mapped[int] = mapped_column(Integer, default=0)
    observed_resource_total: Mapped[int] = mapped_column(Integer, default=0)
    discovered_only_resource_total: Mapped[int] = mapped_column(Integer, default=0)
    resource_occurrence_total: Mapped[int] = mapped_column(Integer, default=0)
    link_occurrence_total: Mapped[int] = mapped_column(Integer, default=0)
    link_edge_total: Mapped[int] = mapped_column(Integer, default=0)
    rendered_page_total: Mapped[int] = mapped_column(Integer, default=0)
    rendered_artifact_total: Mapped[int] = mapped_column(Integer, default=0)
    retry_total: Mapped[int] = mapped_column(Integer, default=0)
    recovered_page_total: Mapped[int] = mapped_column(Integer, default=0)
    error_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    status_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    resource_kind_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    http_status_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    depth_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)

    build: Mapped[ScanProjectionBuild] = relationship(back_populates="summary")
