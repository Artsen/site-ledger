from datetime import datetime
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from app.models.resources import SourceRefresh


class AiDocumentRefresh(Base):
    __tablename__ = "ai_document_refreshes"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_refresh_id: Mapped[int] = mapped_column(
        ForeignKey("source_refreshes.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    root_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    document_discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    document_fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    document_saved_count: Mapped[int] = mapped_column(Integer, default=0)
    document_unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    document_changed_count: Mapped[int] = mapped_column(Integer, default=0)
    document_failed_count: Mapped[int] = mapped_column(Integer, default=0)
    document_skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    reference_count: Mapped[int] = mapped_column(Integer, default=0)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    total_network_bytes: Mapped[int] = mapped_column(Integer, default=0)
    total_retained_bytes: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(128))
    fatal_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    snapshots: Mapped[list["AiDocumentSnapshot"]] = relationship(
        back_populates="refresh", cascade="all, delete-orphan"
    )
    source_refresh: Mapped["SourceRefresh"] = relationship(back_populates="ai_document_refresh")
    validations: Mapped[list["AiDocumentValidation"]] = relationship(
        back_populates="refresh", cascade="all, delete-orphan"
    )


class AiDocumentBlob(Base):
    __tablename__ = "ai_document_blobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    media_type: Mapped[str | None] = mapped_column(String(255))
    encoding: Mapped[str | None] = mapped_column(String(64))
    compression_type: Mapped[str] = mapped_column(String(32), default="gzip")
    raw_byte_size: Mapped[int] = mapped_column(Integer)
    stored_byte_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiDocumentSnapshot(Base):
    __tablename__ = "ai_document_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    refresh_id: Mapped[int] = mapped_column(
        ForeignKey("ai_document_refreshes.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[int] = mapped_column(ForeignKey("web_resources.id"), index=True)
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    parent_depth_min: Mapped[int] = mapped_column(Integer, default=0, index=True)
    document_role: Mapped[str] = mapped_column(String(32), index=True)
    document_kind: Mapped[str] = mapped_column(String(32), index=True)
    classification_rule: Mapped[str] = mapped_column(String(64))
    fetch_state: Mapped[str] = mapped_column(String(32), index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, index=True)
    normalized_mime_type: Mapped[str | None] = mapped_column(String(255), index=True)
    encoding: Mapped[str | None] = mapped_column(String(64))
    response_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    redirect_chain: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    declared_content_length: Mapped[int | None] = mapped_column(Integer)
    network_bytes_transferred: Mapped[int] = mapped_column(Integer, default=0)
    retained_blob_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_document_blobs.id", ondelete="RESTRICT"), index=True
    )
    raw_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    parsed_title: Mapped[str | None] = mapped_column(Text)
    parsed_summary: Mapped[str | None] = mapped_column(Text)
    parsed_intro: Mapped[str | None] = mapped_column(Text)
    parse_state: Mapped[str] = mapped_column(String(32), index=True)
    parse_version: Mapped[str | None] = mapped_column(String(64))
    parse_warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    change_state: Mapped[str] = mapped_column(String(32), default="new", index=True)
    error_type: Mapped[str | None] = mapped_column(String(64), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    refresh: Mapped[AiDocumentRefresh] = relationship(back_populates="snapshots")
    blob: Mapped[AiDocumentBlob | None] = relationship()
    outgoing_references: Mapped[list["AiDocumentReference"]] = relationship(
        foreign_keys="AiDocumentReference.parent_snapshot_id",
        back_populates="parent_snapshot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("refresh_id", "resource_id", name="uq_ai_snapshot_refresh_resource"),
        Index("ix_ai_snapshot_refresh_kind_id", "refresh_id", "document_kind", "id"),
    )


class AiDocumentReference(Base):
    __tablename__ = "ai_document_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("ai_document_snapshots.id", ondelete="CASCADE"), index=True
    )
    target_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("web_resources.id"), index=True
    )
    child_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_document_snapshots.id", ondelete="SET NULL"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    raw_url: Mapped[str] = mapped_column(Text)
    resolved_url: Mapped[str | None] = mapped_column(Text)
    normalized_target_url: Mapped[str | None] = mapped_column(Text, index=True)
    optional: Mapped[bool] = mapped_column(default=False, index=True)
    inferred_role: Mapped[str] = mapped_column(String(32), index=True)
    inferred_kind: Mapped[str] = mapped_column(String(32), index=True)
    classification_rule: Mapped[str] = mapped_column(String(64))
    in_scope: Mapped[bool] = mapped_column(default=False, index=True)
    scope_decision: Mapped[str] = mapped_column(String(64), index=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    discovery_depth: Mapped[int] = mapped_column(Integer, default=1, index=True)
    forms_cycle: Mapped[bool] = mapped_column(default=False, index=True)
    inventory_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("url_source_entries.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parent_snapshot: Mapped[AiDocumentSnapshot] = relationship(
        foreign_keys=[parent_snapshot_id], back_populates="outgoing_references"
    )
    child_snapshot: Mapped[AiDocumentSnapshot | None] = relationship(
        foreign_keys=[child_snapshot_id]
    )

    __table_args__ = (
        UniqueConstraint("parent_snapshot_id", "position", name="uq_ai_reference_position"),
        Index("ix_ai_reference_parent_scope_id", "parent_snapshot_id", "in_scope", "id"),
    )


class AiDocumentValidation(Base):
    __tablename__ = "ai_document_validations"

    id: Mapped[int] = mapped_column(primary_key=True)
    refresh_id: Mapped[int] = mapped_column(
        ForeignKey("ai_document_refreshes.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_document_snapshots.id", ondelete="CASCADE"), index=True
    )
    reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_document_references.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(16), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    refresh: Mapped[AiDocumentRefresh] = relationship(back_populates="validations")
