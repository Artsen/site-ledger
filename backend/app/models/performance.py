from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.database import UTCDateTime as DateTime

if TYPE_CHECKING:
    from app.models.resources import BackgroundJob, WebResource, WebsiteProperty


class PerformanceRun(Base):
    __tablename__ = "performance_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="site_workspace")
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    target_count: Mapped[int] = mapped_column(Integer)
    request_count: Mapped[int] = mapped_column(Integer)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    ready_count: Mapped[int] = mapped_column(Integer, default=0)
    unavailable_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)

    website_property: Mapped[WebsiteProperty] = relationship()
    observations: Mapped[list[PerformanceObservation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[BackgroundJob]] = relationship(
        back_populates="performance_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_performance_runs_site_created", "website_property_id", "created_at", "id"),
    )


class PerformancePayloadBlob(Base):
    __tablename__ = "performance_payload_blobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    content_type: Mapped[str] = mapped_column(String(128), default="application/json")
    compression_type: Mapped[str] = mapped_column(String(32), default="gzip")
    raw_byte_size: Mapped[int] = mapped_column(Integer)
    stored_byte_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    observations: Mapped[list[PerformanceObservation]] = relationship(back_populates="payload_blob")


class PerformanceObservation(Base):
    __tablename__ = "performance_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_run_id: Mapped[int] = mapped_column(
        ForeignKey("performance_runs.id", ondelete="CASCADE"), index=True
    )
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    web_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("web_resources.id", ondelete="RESTRICT"), index=True
    )
    payload_blob_id: Mapped[int | None] = mapped_column(
        ForeignKey("performance_payload_blobs.id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_adapter_version: Mapped[str] = mapped_column(String(64))
    normalization_version: Mapped[str] = mapped_column(String(64))
    target_kind: Mapped[str] = mapped_column(String(16), index=True)
    target_key: Mapped[str] = mapped_column(String(64))
    requested_target: Mapped[str] = mapped_column(Text)
    provider_target: Mapped[str | None] = mapped_column(Text)
    dimension: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    request_descriptor_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    provider_analysis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_period_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provider_product_version: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    error_type: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)

    run: Mapped[PerformanceRun] = relationship(back_populates="observations")
    website_property: Mapped[WebsiteProperty] = relationship()
    web_resource: Mapped[WebResource | None] = relationship()
    payload_blob: Mapped[PerformancePayloadBlob | None] = relationship(
        back_populates="observations"
    )

    __table_args__ = (
        UniqueConstraint(
            "performance_run_id",
            "provider",
            "target_kind",
            "target_key",
            "dimension",
            name="uq_performance_observation_logical_request",
        ),
        Index(
            "ix_performance_observations_site_observed", "website_property_id", "observed_at", "id"
        ),
        Index("ix_performance_observations_page_observed", "web_resource_id", "observed_at", "id"),
        Index(
            "ix_performance_observations_latest",
            "website_property_id",
            "target_kind",
            "target_key",
            "provider",
            "dimension",
            "observed_at",
            "id",
        ),
    )
