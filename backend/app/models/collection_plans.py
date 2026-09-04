from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
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
    from app.models.accessibility import AccessibilityRun
    from app.models.performance import PerformanceRun
    from app.models.rendered import RenderRun
    from app.models.resources import (
        BackgroundJob,
        ContentBlob,
        ResourceSnapshot,
        WebResource,
        WebsiteProperty,
    )


class CollectionPlan(Base):
    __tablename__ = "collection_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    planner_version: Mapped[str] = mapped_column(String(64))
    evidence_domain: Mapped[str] = mapped_column(String(32), index=True)
    target_mode: Mapped[str] = mapped_column(String(32))
    context_identity: Mapped[str] = mapped_column(String(128), index=True)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    active_page_count: Mapped[int] = mapped_column(Integer)
    active_page_universe_sha256: Mapped[str] = mapped_column(String(64))
    eligible_count: Mapped[int] = mapped_column(Integer)
    covered_count_at_creation: Mapped[int] = mapped_column(Integer)
    in_flight_count_at_creation: Mapped[int] = mapped_column(Integer)
    active_collection_count_at_creation: Mapped[int | None] = mapped_column(Integer)
    missing_count_at_creation: Mapped[int] = mapped_column(Integer, default=0)
    selection_reason_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    ineligible_count_at_creation: Mapped[int] = mapped_column(Integer)
    target_count: Mapped[int] = mapped_column(Integer)
    batch_size: Mapped[int] = mapped_column(Integer)
    batch_count: Mapped[int] = mapped_column(Integer)
    target_selection_sha256: Mapped[str] = mapped_column(String(64), index=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    website_property: Mapped[WebsiteProperty] = relationship()
    targets: Mapped[list[CollectionPlanTarget]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="CollectionPlanTarget.position",
    )
    batches: Mapped[list[CollectionPlanBatch]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="CollectionPlanBatch.position",
    )

    __table_args__ = (
        CheckConstraint(
            "evidence_domain IN ('performance', 'accessibility', 'render', 'structured_content')",
            name="ck_collection_plan_evidence_domain",
        ),
        CheckConstraint(
            "target_mode IN ('missing_current', 'refresh_current')",
            name="ck_collection_plan_target_mode",
        ),
        Index(
            "ix_collection_plans_site_created",
            "website_property_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_collection_plans_active_identity",
            "website_property_id",
            "evidence_domain",
            "target_mode",
            "context_identity",
        ),
    )


class CollectionPlanTarget(Base):
    __tablename__ = "collection_plan_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_plan_id: Mapped[int] = mapped_column(
        ForeignKey("collection_plans.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    web_resource_id: Mapped[int] = mapped_column(
        ForeignKey("web_resources.id", ondelete="RESTRICT"), index=True
    )
    requested_url: Mapped[str] = mapped_column(Text)
    selection_reason: Mapped[str] = mapped_column(String(32))
    latest_compatible_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_snapshots.id", ondelete="SET NULL"), index=True
    )
    content_blob_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_blobs.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    plan: Mapped[CollectionPlan] = relationship(back_populates="targets")
    web_resource: Mapped[WebResource] = relationship()
    source_snapshot: Mapped[ResourceSnapshot | None] = relationship()
    content_blob: Mapped[ContentBlob | None] = relationship()

    __table_args__ = (
        UniqueConstraint("collection_plan_id", "position", name="uq_collection_plan_target_pos"),
        UniqueConstraint(
            "collection_plan_id",
            "web_resource_id",
            name="uq_collection_plan_target_resource",
        ),
        Index(
            "ix_collection_plan_targets_plan_resource",
            "collection_plan_id",
            "web_resource_id",
        ),
    )


class CollectionPlanBatch(Base):
    __tablename__ = "collection_plan_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_plan_id: Mapped[int] = mapped_column(
        ForeignKey("collection_plans.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    target_start_position: Mapped[int] = mapped_column(Integer)
    target_count: Mapped[int] = mapped_column(Integer)
    child_kind: Mapped[str] = mapped_column(String(32))
    background_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="SET NULL"), index=True
    )
    performance_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("performance_runs.id", ondelete="SET NULL"), index=True
    )
    accessibility_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("accessibility_runs.id", ondelete="SET NULL"), index=True
    )
    render_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("render_runs.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    plan: Mapped[CollectionPlan] = relationship(back_populates="batches")
    background_job: Mapped[BackgroundJob | None] = relationship()
    performance_run: Mapped[PerformanceRun | None] = relationship()
    accessibility_run: Mapped[AccessibilityRun | None] = relationship()
    render_run: Mapped[RenderRun | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "child_kind IN ('performance', 'accessibility', 'render', 'structured_content')",
            name="ck_collection_plan_batch_child_kind",
        ),
        UniqueConstraint("collection_plan_id", "position", name="uq_collection_plan_batch_pos"),
        Index(
            "ix_collection_plan_batches_plan_position",
            "collection_plan_id",
            "position",
        ),
    )
