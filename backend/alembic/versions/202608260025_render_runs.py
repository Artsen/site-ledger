"""add first-class standalone Render Runs

Revision ID: 202608260025
Revises: 202608250024
Create Date: 2026-08-26 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608260025"
down_revision: str | None = "202608250024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_CONSTRAINT = (
    "(scan_id IS NOT NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL AND render_run_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NOT NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL AND render_run_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NOT NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL AND render_run_id IS NULL "
    "AND job_type = 'scan_comparison_build') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NOT NULL AND accessibility_run_id IS NULL AND render_run_id IS NULL "
    "AND job_type = 'performance_run') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NOT NULL AND render_run_id IS NULL "
    "AND job_type = 'accessibility_run') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL AND render_run_id IS NOT NULL "
    "AND job_type = 'render_run') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL AND render_run_id IS NULL "
    "AND website_property_id IS NOT NULL "
    "AND job_type IN ('category_rule_evaluation', 'structured_content_build'))"
)

PREVIOUS_JOB_CONSTRAINT = (
    "(scan_id IS NOT NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NOT NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL) OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NOT NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL "
    "AND job_type = 'scan_comparison_build') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NOT NULL AND accessibility_run_id IS NULL "
    "AND job_type = 'performance_run') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NOT NULL "
    "AND job_type = 'accessibility_run') OR "
    "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
    "AND performance_run_id IS NULL AND accessibility_run_id IS NULL "
    "AND website_property_id IS NOT NULL "
    "AND job_type IN ('category_rule_evaluation', 'structured_content_build'))"
)


def upgrade() -> None:
    op.create_table(
        "render_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("source_scan_id", sa.Integer()),
        sa.Column("source_render_run_id", sa.Integer()),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("trigger", sa.String(32), nullable=False, server_default="site_workspace"),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("attempted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_summary", sa.Text()),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_scan_id"], ["scans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_render_run_id"], ["render_runs.id"], ondelete="SET NULL"),
    )
    for column in (
        "website_property_id",
        "source_scan_id",
        "source_render_run_id",
        "status",
        "trigger",
    ):
        op.create_index(f"ix_render_runs_{column}", "render_runs", [column])
    op.create_index(
        "ix_render_runs_site_created", "render_runs", ["website_property_id", "created_at", "id"]
    )

    op.create_table(
        "render_run_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("render_run_id", sa.Integer(), nullable=False),
        sa.Column("web_resource_id", sa.Integer(), nullable=False),
        sa.Column("source_snapshot_id", sa.Integer()),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["render_run_id"], ["render_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["web_resource_id"], ["web_resources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"], ["resource_snapshots.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "render_run_id", "web_resource_id", name="uq_render_run_target_resource"
        ),
        sa.UniqueConstraint("render_run_id", "position", name="uq_render_run_target_position"),
    )
    for column in ("render_run_id", "web_resource_id", "source_snapshot_id"):
        op.create_index(f"ix_render_run_targets_{column}", "render_run_targets", [column])
    op.create_index(
        "ix_render_run_targets_run_position",
        "render_run_targets",
        ["render_run_id", "position", "id"],
    )

    naming = {
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    }
    with op.batch_alter_table("rendered_observations", naming_convention=naming) as batch:
        batch.drop_constraint("uq_rendered_observations_snapshot_id", type_="unique")
        batch.drop_index("ix_rendered_observations_snapshot_id")
        batch.drop_constraint(
            "fk_rendered_observations_snapshot_id_resource_snapshots", type_="foreignkey"
        )
        batch.alter_column("snapshot_id", existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key(
            "fk_rendered_observations_snapshot_id_resource_snapshots",
            "resource_snapshots",
            ["snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.add_column(sa.Column("render_run_id", sa.Integer()))
        batch.add_column(sa.Column("render_run_target_id", sa.Integer()))
        batch.add_column(sa.Column("web_resource_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_rendered_observations_render_run_id",
            "render_runs",
            ["render_run_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_rendered_observations_render_run_target_id",
            "render_run_targets",
            ["render_run_target_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_rendered_observations_web_resource_id",
            "web_resources",
            ["web_resource_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_rendered_observations_render_run_id", ["render_run_id"])
        batch.create_index(
            "ix_rendered_observations_render_run_target_id",
            ["render_run_target_id"],
            unique=True,
        )
        batch.create_index("ix_rendered_observations_web_resource_id", ["web_resource_id"])
        batch.create_index("ix_rendered_observations_snapshot_id", ["snapshot_id"])
        batch.create_index(
            "ix_rendered_observations_resource_finished", ["web_resource_id", "finished_at", "id"]
        )
        batch.create_index(
            "ix_rendered_observations_run_outcome",
            ["render_run_id", "capture_state", "navigation_http_status", "id"],
        )

    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.add_column(sa.Column("render_run_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_background_jobs_render_run_id",
            "render_runs",
            ["render_run_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_background_jobs_render_run_id", ["render_run_id"])
        batch.create_check_constraint("ck_background_job_one_subject", JOB_CONSTRAINT)


def downgrade() -> None:
    op.execute("DELETE FROM rendered_observations WHERE render_run_id IS NOT NULL")
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.drop_index("ix_background_jobs_render_run_id")
        batch.drop_constraint("fk_background_jobs_render_run_id", type_="foreignkey")
        batch.drop_column("render_run_id")
        batch.create_check_constraint("ck_background_job_one_subject", PREVIOUS_JOB_CONSTRAINT)
    naming = {
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    }
    with op.batch_alter_table("rendered_observations", naming_convention=naming) as batch:
        batch.drop_index("ix_rendered_observations_run_outcome")
        batch.drop_index("ix_rendered_observations_resource_finished")
        batch.drop_index("ix_rendered_observations_web_resource_id")
        batch.drop_index("ix_rendered_observations_render_run_target_id")
        batch.drop_index("ix_rendered_observations_render_run_id")
        batch.drop_index("ix_rendered_observations_snapshot_id")
        batch.drop_constraint("fk_rendered_observations_web_resource_id", type_="foreignkey")
        batch.drop_constraint("fk_rendered_observations_render_run_target_id", type_="foreignkey")
        batch.drop_constraint("fk_rendered_observations_render_run_id", type_="foreignkey")
        batch.drop_column("web_resource_id")
        batch.drop_column("render_run_target_id")
        batch.drop_column("render_run_id")
        batch.drop_constraint(
            "fk_rendered_observations_snapshot_id_resource_snapshots", type_="foreignkey"
        )
        batch.alter_column("snapshot_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_rendered_observations_snapshot_id_resource_snapshots",
            "resource_snapshots",
            ["snapshot_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint("uq_rendered_observations_snapshot_id", ["snapshot_id"])
        batch.create_index("ix_rendered_observations_snapshot_id", ["snapshot_id"])
    op.drop_table("render_run_targets")
    op.drop_table("render_runs")
