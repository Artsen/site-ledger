"""Add immutable external performance observations.

Revision ID: 202608120021
Revises: 202608070020
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608120021"
down_revision: str | None = "202608070020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERFORMANCE_JOB_CONSTRAINT = (
    "(scan_id IS NOT NULL AND source_refresh_id IS NULL AND "
    "scan_comparison_id IS NULL AND performance_run_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NOT NULL AND "
    "scan_comparison_id IS NULL AND performance_run_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND "
    "scan_comparison_id IS NOT NULL AND performance_run_id IS NULL AND "
    "job_type = 'scan_comparison_build') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND "
    "scan_comparison_id IS NULL AND performance_run_id IS NOT NULL AND "
    "job_type = 'performance_run') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND "
    "scan_comparison_id IS NULL AND performance_run_id IS NULL AND "
    "website_property_id IS NOT NULL AND "
    "job_type IN ('category_rule_evaluation', 'structured_content_build'))"
)

PREVIOUS_JOB_CONSTRAINT = (
    "(scan_id IS NOT NULL AND source_refresh_id IS NULL AND "
    "scan_comparison_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NOT NULL AND "
    "scan_comparison_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND "
    "scan_comparison_id IS NOT NULL AND job_type = 'scan_comparison_build') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND "
    "scan_comparison_id IS NULL AND website_property_id IS NOT NULL AND "
    "job_type IN ('category_rule_evaluation', 'structured_content_build'))"
)


def upgrade() -> None:
    op.create_table(
        "performance_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "website_property_id",
            sa.Integer(),
            sa.ForeignKey("website_properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("trigger", sa.String(32), nullable=False, server_default="site_workspace"),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ready_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unavailable_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_summary", sa.Text()),
    )
    op.create_index(
        "ix_performance_runs_website_property_id", "performance_runs", ["website_property_id"]
    )
    op.create_index("ix_performance_runs_status", "performance_runs", ["status"])
    op.create_index(
        "ix_performance_runs_site_created",
        "performance_runs",
        ["website_property_id", "created_at", "id"],
    )

    op.create_table(
        "performance_payload_blobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "content_type", sa.String(128), nullable=False, server_default="application/json"
        ),
        sa.Column("compression_type", sa.String(32), nullable=False, server_default="gzip"),
        sa.Column("raw_byte_size", sa.Integer(), nullable=False),
        sa.Column("stored_byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "performance_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "performance_run_id",
            sa.Integer(),
            sa.ForeignKey("performance_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "website_property_id",
            sa.Integer(),
            sa.ForeignKey("website_properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "web_resource_id", sa.Integer(), sa.ForeignKey("web_resources.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "payload_blob_id",
            sa.Integer(),
            sa.ForeignKey("performance_payload_blobs.id", ondelete="RESTRICT"),
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_adapter_version", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_key", sa.String(64), nullable=False),
        sa.Column("requested_target", sa.Text(), nullable=False),
        sa.Column("provider_target", sa.Text()),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("request_descriptor_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("normalized_sha256", sa.String(64)),
        sa.Column("provider_analysis_at", sa.DateTime(timezone=True)),
        sa.Column("provider_period_json", sa.JSON()),
        sa.Column("provider_product_version", sa.String(128)),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("error_type", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint(
            "performance_run_id",
            "provider",
            "target_kind",
            "target_key",
            "dimension",
            name="uq_performance_observation_logical_request",
        ),
    )
    for column in (
        "performance_run_id",
        "website_property_id",
        "web_resource_id",
        "payload_blob_id",
        "provider",
        "target_kind",
        "dimension",
        "outcome",
        "normalized_sha256",
        "error_type",
    ):
        op.create_index(
            f"ix_performance_observations_{column}", "performance_observations", [column]
        )
    op.create_index(
        "ix_performance_observations_site_observed",
        "performance_observations",
        ["website_property_id", "observed_at", "id"],
    )
    op.create_index(
        "ix_performance_observations_page_observed",
        "performance_observations",
        ["web_resource_id", "observed_at", "id"],
    )
    op.create_index(
        "ix_performance_observations_latest",
        "performance_observations",
        [
            "website_property_id",
            "target_kind",
            "target_key",
            "provider",
            "dimension",
            "observed_at",
            "id",
        ],
    )

    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.add_column(sa.Column("performance_run_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_background_jobs_performance_run_id",
            "performance_runs",
            ["performance_run_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_background_jobs_performance_run_id", ["performance_run_id"])
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            PERFORMANCE_JOB_CONSTRAINT,
        )


def downgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.drop_index("ix_background_jobs_performance_run_id")
        batch.drop_constraint("fk_background_jobs_performance_run_id", type_="foreignkey")
        batch.drop_column("performance_run_id")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            PREVIOUS_JOB_CONSTRAINT,
        )
    op.drop_table("performance_observations")
    op.drop_table("performance_payload_blobs")
    op.drop_table("performance_runs")
