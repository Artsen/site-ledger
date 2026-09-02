from datetime import datetime
from typing import Any

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
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.database import UTCDateTime as DateTime


class FindingEvaluation(Base):
    __tablename__ = "finding_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    source_scan_id: Mapped[int | None] = mapped_column(
        ForeignKey("scans.id", ondelete="SET NULL"), index=True
    )
    evaluator_version: Mapped[str] = mapped_column(String(64))
    detector_bundle_identity: Mapped[str] = mapped_column(String(128))
    input_fingerprint_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    evidence_horizon_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active_page_count: Mapped[int] = mapped_column(Integer)
    active_page_universe_sha256: Mapped[str] = mapped_column(String(64))
    active_page_resource_ids_json: Mapped[list[int]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    detected_count: Mapped[int] = mapped_column(Integer, default=0)
    clear_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)
    detector_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    reopened_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    assessment_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluation_checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_finding_evaluation_status",
        ),
        Index(
            "ix_finding_evaluations_site_horizon",
            "website_property_id",
            "evidence_horizon_at",
            "id",
        ),
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    web_resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    finding_type: Mapped[str] = mapped_column(String(64), index=True)
    logical_key_version: Mapped[str] = mapped_column(String(64))
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    condition_state: Mapped[str] = mapped_column(String(24), index=True)
    current_severity: Mapped[str | None] = mapped_column(String(16), index=True)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_evaluated_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    current_assessment_id: Mapped[int | None] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "condition_state IN ('detected', 'unknown', 'resolved')",
            name="ck_finding_condition_state",
        ),
        CheckConstraint(
            "current_severity IS NULL OR current_severity IN ('medium', 'high')",
            name="ck_finding_current_severity",
        ),
        UniqueConstraint(
            "website_property_id",
            "finding_type",
            "logical_key_version",
            "web_resource_id",
            name="uq_finding_logical_identity",
        ),
        Index("ix_findings_site_state", "website_property_id", "condition_state"),
    )


class FindingAssessment(Base):
    __tablename__ = "finding_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    finding_evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("finding_evaluations.id", ondelete="CASCADE"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str | None] = mapped_column(String(16))
    evidence_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assessment_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('detected', 'clear', 'unknown')", name="ck_finding_assessment_outcome"
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('medium', 'high')",
            name="ck_finding_assessment_severity",
        ),
        UniqueConstraint(
            "finding_id", "finding_evaluation_id", name="uq_finding_assessment_evaluation"
        ),
        UniqueConstraint("assessment_sha256", name="uq_finding_assessment_sha256"),
    )


class FindingEvidenceReference(Base):
    __tablename__ = "finding_evidence_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_assessment_id: Mapped[int] = mapped_column(
        ForeignKey("finding_assessments.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    evidence_kind: Mapped[str] = mapped_column(String(32), index=True)
    evidence_id: Mapped[int] = mapped_column(Integer, index=True)
    evidence_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "evidence_kind IN ('resource_snapshot', 'scan')",
            name="ck_finding_evidence_kind",
        ),
        UniqueConstraint("finding_assessment_id", "position", name="uq_finding_evidence_position"),
        Index("ix_finding_evidence_pointer", "evidence_kind", "evidence_id"),
    )
