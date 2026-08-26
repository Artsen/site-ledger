from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
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

if TYPE_CHECKING:
    from app.models.resources import (
        BackgroundJob,
        ResourceSnapshot,
        Scan,
        WebResource,
        WebsiteProperty,
    )


class RenderRun(Base):
    __tablename__ = "render_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int | None] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    source_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("scans.id", ondelete="SET NULL"), index=True
    )
    source_render_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("render_runs.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="site_workspace", index=True)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    target_count: Mapped[int] = mapped_column(Integer)
    attempted_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_request_count: Mapped[int] = mapped_column(Integer, default=0)
    artifact_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)

    website_property: Mapped[WebsiteProperty | None] = relationship()
    source_scan: Mapped[Scan | None] = relationship()
    source_render_run: Mapped[RenderRun | None] = relationship(remote_side=[id])
    targets: Mapped[list[RenderRunTarget]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RenderRunTarget.position"
    )
    observations: Mapped[list[RenderedObservation]] = relationship(back_populates="run")
    jobs: Mapped[list[BackgroundJob]] = relationship(
        back_populates="render_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "(trigger = 'scan' AND (source_scan_id IS NOT NULL "
            "OR website_property_id IS NOT NULL)) OR "
            "(trigger IN ('site_workspace', 'page_workspace', 'rerender') "
            "AND website_property_id IS NOT NULL)",
            name="ck_render_run_owner",
        ),
        Index("ix_render_runs_site_created", "website_property_id", "created_at", "id"),
    )


class RenderRunTarget(Base):
    __tablename__ = "render_run_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    render_run_id: Mapped[int] = mapped_column(
        ForeignKey("render_runs.id", ondelete="CASCADE"), index=True
    )
    web_resource_id: Mapped[int] = mapped_column(
        ForeignKey("web_resources.id", ondelete="RESTRICT"), index=True
    )
    source_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL"), index=True
    )
    requested_url: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[RenderRun] = relationship(back_populates="targets")
    web_resource: Mapped[WebResource] = relationship()
    source_snapshot: Mapped[ResourceSnapshot | None] = relationship()
    observation: Mapped[RenderedObservation | None] = relationship(
        back_populates="target", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("render_run_id", "web_resource_id", name="uq_render_run_target_resource"),
        UniqueConstraint("render_run_id", "position", name="uq_render_run_target_position"),
        Index("ix_render_run_targets_run_position", "render_run_id", "position", "id"),
    )


class RenderedObservation(Base):
    __tablename__ = "rendered_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    render_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("render_runs.id", ondelete="CASCADE"), index=True
    )
    render_run_target_id: Mapped[int | None] = mapped_column(
        ForeignKey("render_run_targets.id", ondelete="CASCADE"), unique=True, index=True
    )
    web_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("web_resources.id", ondelete="RESTRICT"), index=True
    )
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL"), index=True
    )
    capture_state: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    navigation_http_status: Mapped[int | None] = mapped_column(Integer)
    document_title: Mapped[str | None] = mapped_column(Text)
    browser_engine: Mapped[str] = mapped_column(String(32), default="chromium")
    browser_version: Mapped[str | None] = mapped_column(String(128))
    playwright_version: Mapped[str | None] = mapped_column(String(64))
    renderer_version: Mapped[str] = mapped_column(String(32))
    browser_policy_version: Mapped[str] = mapped_column(String(32))
    capture_schema_version: Mapped[str] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(Text)
    viewport_width: Mapped[int] = mapped_column(Integer)
    viewport_height: Mapped[int] = mapped_column(Integer)
    device_scale_factor: Mapped[float] = mapped_column(Float)
    locale: Mapped[str] = mapped_column(String(64))
    timezone_id: Mapped[str] = mapped_column(String(128))
    color_scheme: Mapped[str] = mapped_column(String(32))
    reduced_motion: Mapped[str] = mapped_column(String(32))
    readiness_state: Mapped[str | None] = mapped_column(String(64))
    load_event_reached: Mapped[bool] = mapped_column(default=False)
    fonts_ready_reached: Mapped[bool] = mapped_column(default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64))
    network_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_request_count: Mapped[int] = mapped_column(Integer, default=0)
    console_message_count: Mapped[int] = mapped_column(Integer, default=0)
    page_error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    network_truncated: Mapped[bool] = mapped_column(default=False)
    console_truncated: Mapped[bool] = mapped_column(default=False)
    page_errors_truncated: Mapped[bool] = mapped_column(default=False)
    warnings_truncated: Mapped[bool] = mapped_column(default=False)
    total_encoded_network_bytes: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[RenderRun | None] = relationship(back_populates="observations")
    target: Mapped[RenderRunTarget | None] = relationship(back_populates="observation")
    web_resource: Mapped[WebResource | None] = relationship()
    snapshot: Mapped[ResourceSnapshot | None] = relationship(back_populates="rendered_observation")
    artifacts: Mapped[list[RenderedArtifact]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )
    network_entries: Mapped[list[RenderedNetworkEntry]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )
    console_messages: Mapped[list[RenderedConsoleMessage]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )
    page_errors: Mapped[list[RenderedPageError]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_rendered_observations_resource_finished", "web_resource_id", "finished_at", "id"),
        Index(
            "ix_rendered_observations_run_outcome",
            "render_run_id",
            "capture_state",
            "navigation_http_status",
            "id",
        ),
    )


class ArtifactBlob(Base):
    __tablename__ = "artifact_blobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    media_type: Mapped[str] = mapped_column(String(128))
    compression_type: Mapped[str] = mapped_column(String(32))
    raw_byte_size: Mapped[int] = mapped_column(Integer)
    stored_byte_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    artifacts: Mapped[list[RenderedArtifact]] = relationship(back_populates="blob")


class RenderedArtifact(Base):
    __tablename__ = "rendered_artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    rendered_observation_id: Mapped[int] = mapped_column(
        ForeignKey("rendered_observations.id", ondelete="CASCADE"), index=True
    )
    artifact_blob_id: Mapped[int] = mapped_column(ForeignKey("artifact_blobs.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(32), index=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observation: Mapped[RenderedObservation] = relationship(back_populates="artifacts")
    blob: Mapped[ArtifactBlob] = relationship(back_populates="artifacts")
    __table_args__ = (
        UniqueConstraint(
            "rendered_observation_id", "artifact_type", name="uq_rendered_artifact_type"
        ),
    )


class RenderedNetworkEntry(Base):
    __tablename__ = "rendered_network_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    rendered_observation_id: Mapped[int] = mapped_column(
        ForeignKey("rendered_observations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(64))
    redacted_url: Mapped[str] = mapped_column(Text)
    url_sha256: Mapped[str] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(16))
    resource_type: Mapped[str | None] = mapped_column(String(32))
    is_main_navigation: Mapped[bool] = mapped_column(default=False)
    is_navigation_request: Mapped[bool] = mapped_column(default=False)
    request_started_offset_ms: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_status_text: Mapped[str | None] = mapped_column(String(128))
    response_mime_type: Mapped[str | None] = mapped_column(String(255))
    encoded_data_length: Mapped[int | None] = mapped_column(Integer)
    request_headers_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    response_headers_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    blocked_by_policy: Mapped[bool] = mapped_column(default=False)
    policy_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observation: Mapped[RenderedObservation] = relationship(back_populates="network_entries")
    __table_args__ = (
        UniqueConstraint(
            "rendered_observation_id", "sequence", name="uq_rendered_network_sequence"
        ),
        Index(
            "ix_rendered_network_observation_resource", "rendered_observation_id", "resource_type"
        ),
        Index(
            "ix_rendered_network_observation_status", "rendered_observation_id", "response_status"
        ),
        Index(
            "ix_rendered_network_observation_blocked",
            "rendered_observation_id",
            "blocked_by_policy",
        ),
    )


class RenderedConsoleMessage(Base):
    __tablename__ = "rendered_console_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    rendered_observation_id: Mapped[int] = mapped_column(
        ForeignKey("rendered_observations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    message_type: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    line_number: Mapped[int | None] = mapped_column(Integer)
    column_number: Mapped[int | None] = mapped_column(Integer)
    timestamp_offset_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observation: Mapped[RenderedObservation] = relationship(back_populates="console_messages")
    __table_args__ = (
        UniqueConstraint(
            "rendered_observation_id", "sequence", name="uq_rendered_console_sequence"
        ),
    )


class RenderedPageError(Base):
    __tablename__ = "rendered_page_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    rendered_observation_id: Mapped[int] = mapped_column(
        ForeignKey("rendered_observations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    error_name: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    stack: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    timestamp_offset_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observation: Mapped[RenderedObservation] = relationship(back_populates="page_errors")
    __table_args__ = (
        UniqueConstraint("rendered_observation_id", "sequence", name="uq_rendered_error_sequence"),
    )
