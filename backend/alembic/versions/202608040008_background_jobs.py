"""Add durable background jobs.

Revision ID: 202608040008
Revises: 202607310006
Create Date: 2026-08-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608040008"
down_revision: str | None = "202607310006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=True),
        sa.Column("source_refresh_id", sa.Integer(), nullable=True),
        sa.Column("website_property_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("progress_version", sa.Integer(), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("current_operation", sa.Text(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("progress_unit", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=128), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details_json", sa.JSON(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL)",
            name="ck_background_job_one_subject",
        ),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_refresh_id"], ["source_refreshes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"])
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    op.create_index("ix_background_jobs_priority", "background_jobs", ["priority"])
    op.create_index("ix_background_jobs_scan_id", "background_jobs", ["scan_id"])
    op.create_index(
        "ix_background_jobs_source_refresh_id",
        "background_jobs",
        ["source_refresh_id"],
    )
    op.create_index(
        "ix_background_jobs_website_property_id",
        "background_jobs",
        ["website_property_id"],
    )
    op.create_index(
        "ix_background_jobs_lease_expires_at",
        "background_jobs",
        ["lease_expires_at"],
    )
    op.create_index("ix_background_jobs_worker_id", "background_jobs", ["worker_id"])
    op.create_index(
        "ix_background_jobs_cancellation_requested_at",
        "background_jobs",
        ["cancellation_requested_at"],
    )
    op.create_index(
        "ix_background_jobs_claim",
        "background_jobs",
        ["status", "priority", "available_at", "created_at", "id"],
    )
    op.create_index(
        "ix_background_jobs_type_status",
        "background_jobs",
        ["job_type", "status"],
    )
    op.create_index("ix_background_jobs_error_type", "background_jobs", ["error_type"])

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["background_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    op.create_index("ix_job_events_event_type", "job_events", ["event_type"])
    op.create_index("ix_job_events_level", "job_events", ["level"])
    op.create_index("ix_job_events_job_created", "job_events", ["job_id", "created_at", "id"])

    op.create_table(
        "worker_instances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("application_version", sa.String(length=64), nullable=True),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id"),
    )
    op.create_index("ix_worker_instances_last_seen_at", "worker_instances", ["last_seen_at"])
    op.create_index("ix_worker_instances_status", "worker_instances", ["status"])


def downgrade() -> None:
    op.drop_index("ix_worker_instances_status", table_name="worker_instances")
    op.drop_index("ix_worker_instances_last_seen_at", table_name="worker_instances")
    op.drop_table("worker_instances")
    op.drop_index("ix_job_events_job_created", table_name="job_events")
    op.drop_index("ix_job_events_level", table_name="job_events")
    op.drop_index("ix_job_events_event_type", table_name="job_events")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_background_jobs_type_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_error_type", table_name="background_jobs")
    op.drop_index("ix_background_jobs_claim", table_name="background_jobs")
    op.drop_index("ix_background_jobs_cancellation_requested_at", table_name="background_jobs")
    op.drop_index("ix_background_jobs_worker_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_lease_expires_at", table_name="background_jobs")
    op.drop_index("ix_background_jobs_website_property_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_source_refresh_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_scan_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_priority", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_job_type", table_name="background_jobs")
    op.drop_table("background_jobs")
