from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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


class PageCategoryRule(Base):
    __tablename__ = "page_category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("page_categories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    match_mode: Mapped[str] = mapped_column(String(8))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_match_count: Mapped[int] = mapped_column(Integer, default=0)
    current_excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conditions: Mapped[list[PageCategoryRuleCondition]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="PageCategoryRuleCondition.sort_order",
    )

    __table_args__ = (
        CheckConstraint("match_mode IN ('all', 'any')", name="ck_category_rule_match_mode"),
        Index("ix_category_rule_site_active", "website_property_id", "is_active"),
        Index("ix_category_rule_site_category", "website_property_id", "category_id"),
    )


class PageCategoryRuleCondition(Base):
    __tablename__ = "page_category_rule_conditions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("page_category_rules.id", ondelete="CASCADE"), index=True
    )
    target: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(Text)
    negate: Mapped[bool] = mapped_column(Boolean, default=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped[PageCategoryRule] = relationship(back_populates="conditions")

    __table_args__ = (
        CheckConstraint(
            "target IN ('normalized_url','host','path','query','filename')",
            name="ck_category_rule_condition_target",
        ),
        CheckConstraint(
            "operator IN ('equals','starts_with','ends_with','contains','glob','regex')",
            name="ck_category_rule_condition_operator",
        ),
        Index("ix_category_rule_condition_order", "rule_id", "sort_order", "id"),
    )


class PageCategoryAssignmentSupport(Base):
    __tablename__ = "page_category_assignment_supports"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_category_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("page_category_assignments.id", ondelete="CASCADE"), index=True
    )
    support_type: Mapped[str] = mapped_column(String(16))
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("page_category_rules.id", ondelete="CASCADE"), index=True
    )
    support_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(support_type = 'manual' AND rule_id IS NULL AND support_key = 'manual') OR "
            "(support_type = 'rule' AND rule_id IS NOT NULL)",
            name="ck_category_assignment_support_source",
        ),
        UniqueConstraint(
            "page_category_assignment_id", "support_key", name="uq_assignment_support_key"
        ),
        Index(
            "ix_category_assignment_support_rule_assignment",
            "rule_id",
            "page_category_assignment_id",
        ),
    )


class PageCategoryAutomaticExclusion(Base):
    __tablename__ = "page_category_automatic_exclusions"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_page_id: Mapped[int] = mapped_column(
        ForeignKey("site_pages.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("page_categories.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("site_page_id", "category_id", name="uq_page_category_auto_exclusion"),
    )


class PageCategoryRuleRun(Base):
    __tablename__ = "page_category_rule_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)
    trigger_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("page_category_rules.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    rule_count: Mapped[int] = mapped_column(Integer, default=0)
    condition_count: Mapped[int] = mapped_column(Integer, default=0)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    rule_supports_added: Mapped[int] = mapped_column(Integer, default=0)
    rule_supports_removed: Mapped[int] = mapped_column(Integer, default=0)
    effective_assignments_added: Mapped[int] = mapped_column(Integer, default=0)
    effective_assignments_removed: Mapped[int] = mapped_column(Integer, default=0)
    exclusions_suppressing_matches: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evaluator_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_category_rule_run_site_created", "website_property_id", "created_at"),
    )


class PageCategoryRuleRevision(Base):
    __tablename__ = "page_category_rule_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("page_category_rules.id", ondelete="SET NULL"), index=True
    )
    website_property_id: Mapped[int] = mapped_column(
        ForeignKey("website_properties.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("page_categories.id", ondelete="CASCADE"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "action IN ('created','updated','enabled','disabled','deleted')",
            name="ck_category_rule_revision_action",
        ),
        UniqueConstraint("rule_id", "revision_number", name="uq_category_rule_revision"),
    )
