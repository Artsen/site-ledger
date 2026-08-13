from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from app.models.resources import BackgroundJob, WebResource, WebsiteProperty


class AccessibilityRun(Base):
    __tablename__ = "accessibility_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="site_workspace")
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    target_count: Mapped[int] = mapped_column(Integer)
    observation_count: Mapped[int] = mapped_column(Integer)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    ready_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    axe_core_version: Mapped[str] = mapped_column(String(32))
    detector_bundle_sha256: Mapped[str] = mapped_column(String(64))
    integration_version: Mapped[str] = mapped_column(String(64))
    normalization_version: Mapped[str] = mapped_column(String(64))
    ruleset_profile: Mapped[str] = mapped_column(String(64))
    ruleset_rule_count: Mapped[int] = mapped_column(Integer)
    ruleset_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(Text)

    website_property: Mapped[WebsiteProperty] = relationship()
    observations: Mapped[list[AccessibilityObservation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[BackgroundJob]] = relationship(
        back_populates="accessibility_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_accessibility_runs_site_created", "website_property_id", "created_at", "id"),
    )


class AccessibilityPayloadBlob(Base):
    __tablename__ = "accessibility_payload_blobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    content_type: Mapped[str] = mapped_column(String(128), default="application/json")
    compression_type: Mapped[str] = mapped_column(String(32), default="gzip")
    raw_byte_size: Mapped[int] = mapped_column(Integer)
    stored_byte_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    observations: Mapped[list[AccessibilityObservation]] = relationship(
        back_populates="payload_blob"
    )


class AccessibilityObservation(Base):
    __tablename__ = "accessibility_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    accessibility_run_id: Mapped[int] = mapped_column(
        ForeignKey("accessibility_runs.id", ondelete="CASCADE"), index=True
    )
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    web_resource_id: Mapped[int] = mapped_column(
        ForeignKey("web_resources.id", ondelete="RESTRICT"), index=True
    )
    payload_blob_id: Mapped[int | None] = mapped_column(
        ForeignKey("accessibility_payload_blobs.id", ondelete="RESTRICT"), index=True
    )
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    profile: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    axe_core_version: Mapped[str] = mapped_column(String(32))
    detector_bundle_sha256: Mapped[str] = mapped_column(String(64))
    integration_version: Mapped[str] = mapped_column(String(64))
    normalization_version: Mapped[str] = mapped_column(String(64))
    ruleset_profile: Mapped[str] = mapped_column(String(64))
    ruleset_sha256: Mapped[str] = mapped_column(String(64))
    browser_engine: Mapped[str] = mapped_column(String(32), default="chromium")
    browser_version: Mapped[str | None] = mapped_column(String(128))
    playwright_version: Mapped[str | None] = mapped_column(String(32))
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    violation_rule_count: Mapped[int] = mapped_column(Integer, default=0)
    violation_node_count: Mapped[int] = mapped_column(Integer, default=0)
    incomplete_rule_count: Mapped[int] = mapped_column(Integer, default=0)
    incomplete_node_count: Mapped[int] = mapped_column(Integer, default=0)
    pass_rule_count: Mapped[int] = mapped_column(Integer, default=0)
    inapplicable_rule_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    error_type: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)

    run: Mapped[AccessibilityRun] = relationship(back_populates="observations")
    website_property: Mapped[WebsiteProperty] = relationship()
    web_resource: Mapped[WebResource] = relationship()
    payload_blob: Mapped[AccessibilityPayloadBlob | None] = relationship(
        back_populates="observations"
    )
    rules: Mapped[list[AccessibilityRuleEvidence]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "accessibility_run_id",
            "web_resource_id",
            "profile",
            name="uq_accessibility_observation_logical_request",
        ),
        Index(
            "ix_accessibility_observations_site_observed",
            "website_property_id",
            "observed_at",
            "id",
        ),
        Index(
            "ix_accessibility_observations_page_observed", "web_resource_id", "observed_at", "id"
        ),
        Index(
            "ix_accessibility_observations_latest",
            "website_property_id",
            "web_resource_id",
            "profile",
            "observed_at",
            "id",
        ),
    )


class AccessibilityRuleEvidence(Base):
    __tablename__ = "accessibility_rule_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    accessibility_observation_id: Mapped[int] = mapped_column(
        ForeignKey("accessibility_observations.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[str] = mapped_column(String(128), index=True)
    result_type: Mapped[str] = mapped_column(String(32), index=True)
    impact: Mapped[str | None] = mapped_column(String(32), index=True)
    description: Mapped[str] = mapped_column(Text)
    help: Mapped[str] = mapped_column(Text)
    help_url: Mapped[str | None] = mapped_column(Text)
    tags_json: Mapped[list[str]] = mapped_column(JSON)
    node_count: Mapped[int] = mapped_column(Integer)
    rule_evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)

    observation: Mapped[AccessibilityObservation] = relationship(back_populates="rules")
    nodes: Mapped[list[AccessibilityNodeEvidence]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "accessibility_observation_id",
            "result_type",
            "rule_id",
            name="uq_accessibility_rule_evidence",
        ),
        Index(
            "ix_accessibility_rule_current_aggregation",
            "rule_id",
            "result_type",
            "impact",
            "accessibility_observation_id",
        ),
    )


class AccessibilityNodeEvidence(Base):
    __tablename__ = "accessibility_node_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    accessibility_rule_evidence_id: Mapped[int] = mapped_column(
        ForeignKey("accessibility_rule_evidence.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    impact: Mapped[str | None] = mapped_column(String(32))
    target_json: Mapped[list[Any]] = mapped_column(JSON)
    html_snippet: Mapped[str] = mapped_column(Text)
    html_original_length: Mapped[int] = mapped_column(Integer)
    html_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_summary: Mapped[str] = mapped_column(Text)
    node_evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)

    rule: Mapped[AccessibilityRuleEvidence] = relationship(back_populates="nodes")

    __table_args__ = (
        UniqueConstraint(
            "accessibility_rule_evidence_id", "position", name="uq_accessibility_node_position"
        ),
    )
