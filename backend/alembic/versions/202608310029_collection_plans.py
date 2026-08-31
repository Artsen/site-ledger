"""Add current-evidence Collection Plans.

Revision ID: 202608310029
Revises: 202608280028
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608310029"
down_revision: str | None = "202608280028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collection_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "website_property_id",
            sa.Integer(),
            sa.ForeignKey("website_properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("planner_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_domain", sa.String(length=32), nullable=False),
        sa.Column("target_mode", sa.String(length=32), nullable=False),
        sa.Column("context_identity", sa.String(length=128), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("active_page_count", sa.Integer(), nullable=False),
        sa.Column("active_page_universe_sha256", sa.String(length=64), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("covered_count_at_creation", sa.Integer(), nullable=False),
        sa.Column("in_flight_count_at_creation", sa.Integer(), nullable=False),
        sa.Column("ineligible_count_at_creation", sa.Integer(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("batch_count", sa.Integer(), nullable=False),
        sa.Column("target_selection_sha256", sa.String(length=64), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "evidence_domain IN ('performance', 'accessibility', 'render', 'structured_content')",
            name="ck_collection_plan_evidence_domain",
        ),
        sa.CheckConstraint(
            "target_mode = 'missing_current'", name="ck_collection_plan_target_mode"
        ),
    )
    op.create_index(
        "ix_collection_plans_website_property_id",
        "collection_plans",
        ["website_property_id"],
    )
    op.create_index("ix_collection_plans_evidence_domain", "collection_plans", ["evidence_domain"])
    op.create_index(
        "ix_collection_plans_context_identity", "collection_plans", ["context_identity"]
    )
    op.create_index(
        "ix_collection_plans_target_selection_sha256",
        "collection_plans",
        ["target_selection_sha256"],
    )
    op.create_index(
        "ix_collection_plans_cancellation_requested_at",
        "collection_plans",
        ["cancellation_requested_at"],
    )
    op.create_index(
        "ix_collection_plans_site_created",
        "collection_plans",
        ["website_property_id", "created_at", "id"],
    )
    op.create_index(
        "ix_collection_plans_active_identity",
        "collection_plans",
        ["website_property_id", "evidence_domain", "target_mode", "context_identity"],
    )

    op.create_table(
        "collection_plan_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "collection_plan_id",
            sa.Integer(),
            sa.ForeignKey("collection_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "web_resource_id",
            sa.Integer(),
            sa.ForeignKey("web_resources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("selection_reason", sa.String(length=32), nullable=False),
        sa.Column("target_context_json", sa.JSON(), nullable=False),
        sa.Column(
            "source_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("resource_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "content_blob_id",
            sa.Integer(),
            sa.ForeignKey("content_blobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("collection_plan_id", "position", name="uq_collection_plan_target_pos"),
        sa.UniqueConstraint(
            "collection_plan_id",
            "web_resource_id",
            name="uq_collection_plan_target_resource",
        ),
    )
    for column in (
        "collection_plan_id",
        "web_resource_id",
        "source_snapshot_id",
        "content_blob_id",
    ):
        op.create_index(f"ix_collection_plan_targets_{column}", "collection_plan_targets", [column])
    op.create_index(
        "ix_collection_plan_targets_plan_resource",
        "collection_plan_targets",
        ["collection_plan_id", "web_resource_id"],
    )

    op.create_table(
        "collection_plan_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "collection_plan_id",
            sa.Integer(),
            sa.ForeignKey("collection_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("target_start_position", sa.Integer(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("child_kind", sa.String(length=32), nullable=False),
        sa.Column(
            "background_job_id",
            sa.Integer(),
            sa.ForeignKey("background_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "performance_run_id",
            sa.Integer(),
            sa.ForeignKey("performance_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "accessibility_run_id",
            sa.Integer(),
            sa.ForeignKey("accessibility_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "render_run_id",
            sa.Integer(),
            sa.ForeignKey("render_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "child_kind IN ('performance', 'accessibility', 'render', 'structured_content')",
            name="ck_collection_plan_batch_child_kind",
        ),
        sa.UniqueConstraint("collection_plan_id", "position", name="uq_collection_plan_batch_pos"),
    )
    for column in (
        "collection_plan_id",
        "background_job_id",
        "performance_run_id",
        "accessibility_run_id",
        "render_run_id",
    ):
        op.create_index(f"ix_collection_plan_batches_{column}", "collection_plan_batches", [column])
    op.create_index(
        "ix_collection_plan_batches_plan_position",
        "collection_plan_batches",
        ["collection_plan_id", "position"],
    )


def downgrade() -> None:
    op.drop_table("collection_plan_batches")
    op.drop_table("collection_plan_targets")
    op.drop_table("collection_plans")
