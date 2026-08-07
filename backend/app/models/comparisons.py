from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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
from app.database import UTCDateTime as DateTime


class ScanComparison(Base):
    __tablename__ = "scan_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    baseline_scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True
    )
    target_scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True
    )
    current_build_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_comparison_builds.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    current_build: Mapped[ScanComparisonBuild | None] = relationship(
        foreign_keys=[current_build_id], post_update=True
    )
    builds: Mapped[list[ScanComparisonBuild]] = relationship(
        back_populates="comparison",
        foreign_keys="ScanComparisonBuild.scan_comparison_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "website_property_id",
            "baseline_scan_id",
            "target_scan_id",
            name="uq_scan_comparison_direction",
        ),
        Index("ix_scan_comparison_site_created", "website_property_id", "created_at"),
    )


class ScanComparisonBuild(Base):
    __tablename__ = "scan_comparison_builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_comparison_id: Mapped[int] = mapped_column(
        ForeignKey("scan_comparisons.id", ondelete="CASCADE"), index=True
    )
    comparison_version: Mapped[str] = mapped_column(String(64), index=True)
    algorithm_identity: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    active_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    baseline_projection_build_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_projection_builds.id", ondelete="SET NULL"), index=True
    )
    target_projection_build_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_projection_builds.id", ondelete="SET NULL"), index=True
    )
    baseline_projection_version: Mapped[str | None] = mapped_column(String(64))
    target_projection_version: Mapped[str | None] = mapped_column(String(64))
    baseline_projection_algorithm_identity: Mapped[str | None] = mapped_column(String(255))
    target_projection_algorithm_identity: Mapped[str | None] = mapped_column(String(255))
    baseline_projection_checksum: Mapped[str | None] = mapped_column(String(64))
    target_projection_checksum: Mapped[str | None] = mapped_column(String(64))
    baseline_projection_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_projection_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_scope_fingerprint: Mapped[str | None] = mapped_column(String(64))
    target_scope_fingerprint: Mapped[str | None] = mapped_column(String(64))
    baseline_seed_fingerprint: Mapped[str | None] = mapped_column(String(64))
    target_seed_fingerprint: Mapped[str | None] = mapped_column(String(64))
    coverage_state: Mapped[str | None] = mapped_column(String(32), index=True)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    comparison_checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    build_duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    page_result_count: Mapped[int] = mapped_column(Integer, default=0)
    resource_result_count: Mapped[int] = mapped_column(Integer, default=0)
    link_result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    comparison: Mapped[ScanComparison] = relationship(
        back_populates="builds", foreign_keys=[scan_comparison_id]
    )
    pages: Mapped[list[ScanComparisonPageResult]] = relationship(
        back_populates="build", cascade="all, delete-orphan"
    )
    resources: Mapped[list[ScanComparisonResourceResult]] = relationship(
        back_populates="build", cascade="all, delete-orphan"
    )
    links: Mapped[list[ScanComparisonLinkResult]] = relationship(
        back_populates="build", cascade="all, delete-orphan"
    )
    summary: Mapped[ScanComparisonSummary | None] = relationship(
        back_populates="build", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        Index(
            "ix_comparison_build_comparison_version_status",
            "scan_comparison_id",
            "comparison_version",
            "status",
        ),
    )


class ScanComparisonPageResult(Base):
    __tablename__ = "scan_comparison_page_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_comparison_builds.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    normalized_url: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    baseline_page_projection_id: Mapped[int | None] = mapped_column(Integer)
    target_page_projection_id: Mapped[int | None] = mapped_column(Integer)
    baseline_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL"), index=True
    )
    target_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL"), index=True
    )
    presence_state: Mapped[str] = mapped_column(String(32), index=True)
    baseline_presence_detail: Mapped[str] = mapped_column(String(32))
    target_presence_detail: Mapped[str] = mapped_column(String(32))
    change_state: Mapped[str] = mapped_column(String(32), index=True)
    content_state: Mapped[str] = mapped_column(String(32), index=True)
    head_state: Mapped[str] = mapped_column(String(32), index=True)
    changed_field_count: Mapped[int] = mapped_column(Integer, default=0)
    content_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    head_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    http_status_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    fetch_state_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    final_url_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    redirect_state_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    content_type_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    title_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    canonical_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    robots_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    language_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    depth_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    inbound_links_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    outbound_links_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    embedded_resources_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    rendered_state_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    rendered_counts_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    baseline_http_status: Mapped[int | None] = mapped_column(Integer)
    target_http_status: Mapped[int | None] = mapped_column(Integer, index=True)
    baseline_content_hash: Mapped[str | None] = mapped_column(String(64))
    target_content_hash: Mapped[str | None] = mapped_column(String(64))
    baseline_head_hash: Mapped[str | None] = mapped_column(String(64))
    target_head_hash: Mapped[str | None] = mapped_column(String(64))
    response_time_ms_delta: Mapped[int | None] = mapped_column(Integer)
    network_bytes_delta: Mapped[int | None] = mapped_column(Integer)
    raw_html_size_delta: Mapped[int | None] = mapped_column(Integer)
    stored_html_size_delta: Mapped[int | None] = mapped_column(Integer)
    outgoing_edges_newly_observed: Mapped[int] = mapped_column(Integer, default=0)
    outgoing_edges_not_observed: Mapped[int] = mapped_column(Integer, default=0)
    outgoing_edges_changed: Mapped[int] = mapped_column(Integer, default=0)
    incoming_edges_newly_observed: Mapped[int] = mapped_column(Integer, default=0)
    incoming_edges_not_observed: Mapped[int] = mapped_column(Integer, default=0)
    incoming_edges_changed: Mapped[int] = mapped_column(Integer, default=0)
    baseline_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    target_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    build: Mapped[ScanComparisonBuild] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint("comparison_build_id", "resource_id", name="uq_comparison_page_resource"),
        Index("ix_comparison_page_build_url", "comparison_build_id", "normalized_url"),
        Index("ix_comparison_page_build_presence", "comparison_build_id", "presence_state"),
        Index("ix_comparison_page_build_change", "comparison_build_id", "change_state"),
        Index("ix_comparison_page_build_content", "comparison_build_id", "content_state"),
        Index("ix_comparison_page_build_host", "comparison_build_id", "host"),
        Index(
            "ix_comparison_page_build_changed_count", "comparison_build_id", "changed_field_count"
        ),
    )


class ScanComparisonResourceResult(Base):
    __tablename__ = "scan_comparison_resource_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_comparison_builds.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    normalized_url: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(Text)
    baseline_resource_projection_id: Mapped[int | None] = mapped_column(Integer)
    target_resource_projection_id: Mapped[int | None] = mapped_column(Integer)
    baseline_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL")
    )
    target_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL")
    )
    presence_state: Mapped[str] = mapped_column(String(32), index=True)
    change_state: Mapped[str] = mapped_column(String(32), index=True)
    changed_field_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_kind: Mapped[str | None] = mapped_column(String(32))
    target_kind: Mapped[str | None] = mapped_column(String(32), index=True)
    baseline_mime_type: Mapped[str | None] = mapped_column(String(255))
    target_mime_type: Mapped[str | None] = mapped_column(String(255))
    baseline_http_status: Mapped[int | None] = mapped_column(Integer)
    target_http_status: Mapped[int | None] = mapped_column(Integer, index=True)
    status_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_state_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    occurrence_delta: Mapped[int | None] = mapped_column(Integer, index=True)
    source_page_delta: Mapped[int | None] = mapped_column(Integer)
    declared_size_delta: Mapped[int | None] = mapped_column(Integer)
    baseline_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    target_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    build: Mapped[ScanComparisonBuild] = relationship(back_populates="resources")

    __table_args__ = (
        UniqueConstraint("comparison_build_id", "resource_id", name="uq_comparison_resource"),
        Index("ix_comparison_resource_build_url", "comparison_build_id", "normalized_url"),
        Index("ix_comparison_resource_build_presence", "comparison_build_id", "presence_state"),
        Index("ix_comparison_resource_build_change", "comparison_build_id", "change_state"),
        Index("ix_comparison_resource_build_host", "comparison_build_id", "host"),
    )


class ScanComparisonLinkResult(Base):
    __tablename__ = "scan_comparison_link_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_comparison_builds.id", ondelete="CASCADE"), index=True
    )
    source_resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    target_resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    target_url: Mapped[str] = mapped_column(Text)
    baseline_link_projection_id: Mapped[int | None] = mapped_column(Integer)
    target_link_projection_id: Mapped[int | None] = mapped_column(Integer)
    baseline_source_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL")
    )
    target_source_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL")
    )
    presence_state: Mapped[str] = mapped_column(String(32), index=True)
    change_state: Mapped[str] = mapped_column(String(32), index=True)
    changed_field_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    target_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    occurrence_delta: Mapped[int] = mapped_column(Integer, default=0, index=True)
    baseline_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    target_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    build: Mapped[ScanComparisonBuild] = relationship(back_populates="links")

    __table_args__ = (
        UniqueConstraint(
            "comparison_build_id",
            "source_resource_id",
            "target_resource_id",
            name="uq_comparison_link_edge",
        ),
        Index("ix_comparison_link_build_source", "comparison_build_id", "source_resource_id"),
        Index("ix_comparison_link_build_target", "comparison_build_id", "target_resource_id"),
        Index("ix_comparison_link_build_presence", "comparison_build_id", "presence_state"),
        Index("ix_comparison_link_build_change", "comparison_build_id", "change_state"),
    )


class ScanComparisonSummary(Base):
    __tablename__ = "scan_comparison_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_build_id: Mapped[int] = mapped_column(
        ForeignKey("scan_comparison_builds.id", ondelete="CASCADE"), unique=True
    )
    page_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resource_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    link_counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scan_summary_delta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    build: Mapped[ScanComparisonBuild] = relationship(back_populates="summary")
