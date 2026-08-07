"""Add deterministic Scan comparisons.

Revision ID: 202608060018
Revises: 202608060017
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608060018"
down_revision: str | None = "202608060017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Build and logical identity form a deliberate cyclic pointer. SQLite permits
    # creating the build table first and resolving its comparison FK once both exist.
    op.create_table(
        "scan_comparison_builds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_comparison_id", sa.Integer(), nullable=False),
        sa.Column("comparison_version", sa.String(length=64), nullable=False),
        sa.Column("algorithm_identity", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_key", sa.String(length=255), nullable=True),
        sa.Column("baseline_projection_build_id", sa.Integer(), nullable=True),
        sa.Column("target_projection_build_id", sa.Integer(), nullable=True),
        sa.Column("baseline_projection_version", sa.String(length=64), nullable=True),
        sa.Column("target_projection_version", sa.String(length=64), nullable=True),
        sa.Column("baseline_projection_algorithm_identity", sa.String(length=255), nullable=True),
        sa.Column("target_projection_algorithm_identity", sa.String(length=255), nullable=True),
        sa.Column("baseline_projection_checksum", sa.String(length=64), nullable=True),
        sa.Column("target_projection_checksum", sa.String(length=64), nullable=True),
        sa.Column("baseline_projection_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_projection_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_scope_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("target_scope_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("baseline_seed_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("target_seed_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("coverage_state", sa.String(length=32), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("comparison_checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("build_duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("page_result_count", sa.Integer(), nullable=False),
        sa.Column("resource_result_count", sa.Integer(), nullable=False),
        sa.Column("link_result_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["baseline_projection_build_id"], ["scan_projection_builds.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["scan_comparison_id"], ["scan_comparisons.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_projection_build_id"], ["scan_projection_builds.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_key"),
    )
    op.create_index(
        "ix_comparison_build_comparison_version_status",
        "scan_comparison_builds",
        ["scan_comparison_id", "comparison_version", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_builds_baseline_projection_build_id"),
        "scan_comparison_builds",
        ["baseline_projection_build_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_builds_comparison_checksum_sha256"),
        "scan_comparison_builds",
        ["comparison_checksum_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_builds_comparison_version"),
        "scan_comparison_builds",
        ["comparison_version"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_builds_coverage_state"),
        "scan_comparison_builds",
        ["coverage_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_builds_scan_comparison_id"),
        "scan_comparison_builds",
        ["scan_comparison_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_builds_status"), "scan_comparison_builds", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_scan_comparison_builds_target_projection_build_id"),
        "scan_comparison_builds",
        ["target_projection_build_id"],
        unique=False,
    )
    op.create_table(
        "scan_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("baseline_scan_id", sa.Integer(), nullable=False),
        sa.Column("target_scan_id", sa.Integer(), nullable=False),
        sa.Column("current_build_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["baseline_scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["current_build_id"], ["scan_comparison_builds.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["target_scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("current_build_id"),
        sa.UniqueConstraint(
            "website_property_id",
            "baseline_scan_id",
            "target_scan_id",
            name="uq_scan_comparison_direction",
        ),
    )
    op.create_index(
        "ix_scan_comparison_site_created",
        "scan_comparisons",
        ["website_property_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparisons_baseline_scan_id"),
        "scan_comparisons",
        ["baseline_scan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparisons_target_scan_id"),
        "scan_comparisons",
        ["target_scan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparisons_website_property_id"),
        "scan_comparisons",
        ["website_property_id"],
        unique=False,
    )
    op.create_table(
        "scan_comparison_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comparison_build_id", sa.Integer(), nullable=False),
        sa.Column("page_counts_json", sa.JSON(), nullable=False),
        sa.Column("resource_counts_json", sa.JSON(), nullable=False),
        sa.Column("link_counts_json", sa.JSON(), nullable=False),
        sa.Column("scan_summary_delta_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["comparison_build_id"], ["scan_comparison_builds.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comparison_build_id"),
    )
    op.create_table(
        "scan_comparison_link_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comparison_build_id", sa.Integer(), nullable=False),
        sa.Column("source_resource_id", sa.Integer(), nullable=False),
        sa.Column("target_resource_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("baseline_link_projection_id", sa.Integer(), nullable=True),
        sa.Column("target_link_projection_id", sa.Integer(), nullable=True),
        sa.Column("baseline_source_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("target_source_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("presence_state", sa.String(length=32), nullable=False),
        sa.Column("change_state", sa.String(length=32), nullable=False),
        sa.Column("changed_field_count", sa.Integer(), nullable=False),
        sa.Column("baseline_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("target_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("occurrence_delta", sa.Integer(), nullable=False),
        sa.Column("baseline_json", sa.JSON(), nullable=True),
        sa.Column("target_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["baseline_source_snapshot_id"], ["resource_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_build_id"], ["scan_comparison_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_resource_id"],
            ["web_resources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_resource_id"],
            ["web_resources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_source_snapshot_id"], ["resource_snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_build_id",
            "source_resource_id",
            "target_resource_id",
            name="uq_comparison_link_edge",
        ),
    )
    op.create_index(
        "ix_comparison_link_build_change",
        "scan_comparison_link_results",
        ["comparison_build_id", "change_state"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_link_build_presence",
        "scan_comparison_link_results",
        ["comparison_build_id", "presence_state"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_link_build_source",
        "scan_comparison_link_results",
        ["comparison_build_id", "source_resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_link_build_target",
        "scan_comparison_link_results",
        ["comparison_build_id", "target_resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_link_results_change_state"),
        "scan_comparison_link_results",
        ["change_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_link_results_comparison_build_id"),
        "scan_comparison_link_results",
        ["comparison_build_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_link_results_occurrence_delta"),
        "scan_comparison_link_results",
        ["occurrence_delta"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_link_results_presence_state"),
        "scan_comparison_link_results",
        ["presence_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_link_results_source_resource_id"),
        "scan_comparison_link_results",
        ["source_resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_link_results_target_resource_id"),
        "scan_comparison_link_results",
        ["target_resource_id"],
        unique=False,
    )
    op.create_table(
        "scan_comparison_page_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comparison_build_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("baseline_page_projection_id", sa.Integer(), nullable=True),
        sa.Column("target_page_projection_id", sa.Integer(), nullable=True),
        sa.Column("baseline_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("target_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("presence_state", sa.String(length=32), nullable=False),
        sa.Column("baseline_presence_detail", sa.String(length=32), nullable=False),
        sa.Column("target_presence_detail", sa.String(length=32), nullable=False),
        sa.Column("change_state", sa.String(length=32), nullable=False),
        sa.Column("content_state", sa.String(length=32), nullable=False),
        sa.Column("head_state", sa.String(length=32), nullable=False),
        sa.Column("changed_field_count", sa.Integer(), nullable=False),
        sa.Column("content_changed", sa.Boolean(), nullable=False),
        sa.Column("head_changed", sa.Boolean(), nullable=False),
        sa.Column("http_status_changed", sa.Boolean(), nullable=False),
        sa.Column("fetch_state_changed", sa.Boolean(), nullable=False),
        sa.Column("final_url_changed", sa.Boolean(), nullable=False),
        sa.Column("redirect_state_changed", sa.Boolean(), nullable=False),
        sa.Column("content_type_changed", sa.Boolean(), nullable=False),
        sa.Column("title_changed", sa.Boolean(), nullable=False),
        sa.Column("canonical_changed", sa.Boolean(), nullable=False),
        sa.Column("robots_changed", sa.Boolean(), nullable=False),
        sa.Column("language_changed", sa.Boolean(), nullable=False),
        sa.Column("depth_changed", sa.Boolean(), nullable=False),
        sa.Column("inbound_links_changed", sa.Boolean(), nullable=False),
        sa.Column("outbound_links_changed", sa.Boolean(), nullable=False),
        sa.Column("embedded_resources_changed", sa.Boolean(), nullable=False),
        sa.Column("rendered_state_changed", sa.Boolean(), nullable=False),
        sa.Column("rendered_counts_changed", sa.Boolean(), nullable=False),
        sa.Column("baseline_http_status", sa.Integer(), nullable=True),
        sa.Column("target_http_status", sa.Integer(), nullable=True),
        sa.Column("baseline_content_hash", sa.String(length=64), nullable=True),
        sa.Column("target_content_hash", sa.String(length=64), nullable=True),
        sa.Column("baseline_head_hash", sa.String(length=64), nullable=True),
        sa.Column("target_head_hash", sa.String(length=64), nullable=True),
        sa.Column("response_time_ms_delta", sa.Integer(), nullable=True),
        sa.Column("network_bytes_delta", sa.Integer(), nullable=True),
        sa.Column("raw_html_size_delta", sa.Integer(), nullable=True),
        sa.Column("stored_html_size_delta", sa.Integer(), nullable=True),
        sa.Column("outgoing_edges_newly_observed", sa.Integer(), nullable=False),
        sa.Column("outgoing_edges_not_observed", sa.Integer(), nullable=False),
        sa.Column("outgoing_edges_changed", sa.Integer(), nullable=False),
        sa.Column("incoming_edges_newly_observed", sa.Integer(), nullable=False),
        sa.Column("incoming_edges_not_observed", sa.Integer(), nullable=False),
        sa.Column("incoming_edges_changed", sa.Integer(), nullable=False),
        sa.Column("baseline_json", sa.JSON(), nullable=True),
        sa.Column("target_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["baseline_snapshot_id"], ["resource_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_build_id"], ["scan_comparison_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["web_resources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_snapshot_id"], ["resource_snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_build_id", "resource_id", name="uq_comparison_page_resource"
        ),
    )
    op.create_index(
        "ix_comparison_page_build_change",
        "scan_comparison_page_results",
        ["comparison_build_id", "change_state"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_page_build_changed_count",
        "scan_comparison_page_results",
        ["comparison_build_id", "changed_field_count"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_page_build_content",
        "scan_comparison_page_results",
        ["comparison_build_id", "content_state"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_page_build_host",
        "scan_comparison_page_results",
        ["comparison_build_id", "host"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_page_build_presence",
        "scan_comparison_page_results",
        ["comparison_build_id", "presence_state"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_page_build_url",
        "scan_comparison_page_results",
        ["comparison_build_id", "normalized_url"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_baseline_snapshot_id"),
        "scan_comparison_page_results",
        ["baseline_snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_change_state"),
        "scan_comparison_page_results",
        ["change_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_comparison_build_id"),
        "scan_comparison_page_results",
        ["comparison_build_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_content_state"),
        "scan_comparison_page_results",
        ["content_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_head_state"),
        "scan_comparison_page_results",
        ["head_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_presence_state"),
        "scan_comparison_page_results",
        ["presence_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_resource_id"),
        "scan_comparison_page_results",
        ["resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_target_http_status"),
        "scan_comparison_page_results",
        ["target_http_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_page_results_target_snapshot_id"),
        "scan_comparison_page_results",
        ["target_snapshot_id"],
        unique=False,
    )
    op.create_table(
        "scan_comparison_resource_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comparison_build_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("baseline_resource_projection_id", sa.Integer(), nullable=True),
        sa.Column("target_resource_projection_id", sa.Integer(), nullable=True),
        sa.Column("baseline_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("target_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("presence_state", sa.String(length=32), nullable=False),
        sa.Column("change_state", sa.String(length=32), nullable=False),
        sa.Column("changed_field_count", sa.Integer(), nullable=False),
        sa.Column("baseline_kind", sa.String(length=32), nullable=True),
        sa.Column("target_kind", sa.String(length=32), nullable=True),
        sa.Column("baseline_mime_type", sa.String(length=255), nullable=True),
        sa.Column("target_mime_type", sa.String(length=255), nullable=True),
        sa.Column("baseline_http_status", sa.Integer(), nullable=True),
        sa.Column("target_http_status", sa.Integer(), nullable=True),
        sa.Column("status_changed", sa.Boolean(), nullable=False),
        sa.Column("observed_state_changed", sa.Boolean(), nullable=False),
        sa.Column("occurrence_delta", sa.Integer(), nullable=True),
        sa.Column("source_page_delta", sa.Integer(), nullable=True),
        sa.Column("declared_size_delta", sa.Integer(), nullable=True),
        sa.Column("baseline_json", sa.JSON(), nullable=True),
        sa.Column("target_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["baseline_snapshot_id"], ["resource_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_build_id"], ["scan_comparison_builds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["web_resources.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_snapshot_id"], ["resource_snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comparison_build_id", "resource_id", name="uq_comparison_resource"),
    )
    op.create_index(
        "ix_comparison_resource_build_change",
        "scan_comparison_resource_results",
        ["comparison_build_id", "change_state"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_resource_build_host",
        "scan_comparison_resource_results",
        ["comparison_build_id", "host"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_resource_build_presence",
        "scan_comparison_resource_results",
        ["comparison_build_id", "presence_state"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_resource_build_url",
        "scan_comparison_resource_results",
        ["comparison_build_id", "normalized_url"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_resource_results_change_state"),
        "scan_comparison_resource_results",
        ["change_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_resource_results_comparison_build_id"),
        "scan_comparison_resource_results",
        ["comparison_build_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_resource_results_occurrence_delta"),
        "scan_comparison_resource_results",
        ["occurrence_delta"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_resource_results_presence_state"),
        "scan_comparison_resource_results",
        ["presence_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_resource_results_resource_id"),
        "scan_comparison_resource_results",
        ["resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_resource_results_target_http_status"),
        "scan_comparison_resource_results",
        ["target_http_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_comparison_resource_results_target_kind"),
        "scan_comparison_resource_results",
        ["target_kind"],
        unique=False,
    )
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.add_column(sa.Column("scan_comparison_id", sa.Integer()))
        batch.create_index("ix_background_jobs_scan_comparison_id", ["scan_comparison_id"])
        batch.create_foreign_key(
            "fk_background_jobs_scan_comparison_id",
            "scan_comparisons",
            ["scan_comparison_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL "
            "AND scan_comparison_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL "
            "AND scan_comparison_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL "
            "AND scan_comparison_id IS NOT NULL AND job_type = 'scan_comparison_build') OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
            "AND website_property_id IS NOT NULL AND job_type = 'category_rule_evaluation')",
        )


def downgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.drop_constraint("fk_background_jobs_scan_comparison_id", type_="foreignkey")
        batch.drop_index("ix_background_jobs_scan_comparison_id")
        batch.drop_column("scan_comparison_id")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL AND website_property_id IS NOT NULL "
            "AND job_type = 'category_rule_evaluation')",
        )
    op.drop_index(
        op.f("ix_scan_comparison_resource_results_target_kind"),
        table_name="scan_comparison_resource_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_resource_results_target_http_status"),
        table_name="scan_comparison_resource_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_resource_results_resource_id"),
        table_name="scan_comparison_resource_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_resource_results_presence_state"),
        table_name="scan_comparison_resource_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_resource_results_occurrence_delta"),
        table_name="scan_comparison_resource_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_resource_results_comparison_build_id"),
        table_name="scan_comparison_resource_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_resource_results_change_state"),
        table_name="scan_comparison_resource_results",
    )
    op.drop_index("ix_comparison_resource_build_url", table_name="scan_comparison_resource_results")
    op.drop_index(
        "ix_comparison_resource_build_presence", table_name="scan_comparison_resource_results"
    )
    op.drop_index(
        "ix_comparison_resource_build_host", table_name="scan_comparison_resource_results"
    )
    op.drop_index(
        "ix_comparison_resource_build_change", table_name="scan_comparison_resource_results"
    )
    op.drop_table("scan_comparison_resource_results")
    op.drop_index(
        op.f("ix_scan_comparison_page_results_target_snapshot_id"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_target_http_status"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_resource_id"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_presence_state"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_head_state"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_content_state"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_comparison_build_id"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_change_state"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_page_results_baseline_snapshot_id"),
        table_name="scan_comparison_page_results",
    )
    op.drop_index("ix_comparison_page_build_url", table_name="scan_comparison_page_results")
    op.drop_index("ix_comparison_page_build_presence", table_name="scan_comparison_page_results")
    op.drop_index("ix_comparison_page_build_host", table_name="scan_comparison_page_results")
    op.drop_index("ix_comparison_page_build_content", table_name="scan_comparison_page_results")
    op.drop_index(
        "ix_comparison_page_build_changed_count", table_name="scan_comparison_page_results"
    )
    op.drop_index("ix_comparison_page_build_change", table_name="scan_comparison_page_results")
    op.drop_table("scan_comparison_page_results")
    op.drop_index(
        op.f("ix_scan_comparison_link_results_target_resource_id"),
        table_name="scan_comparison_link_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_link_results_source_resource_id"),
        table_name="scan_comparison_link_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_link_results_presence_state"),
        table_name="scan_comparison_link_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_link_results_occurrence_delta"),
        table_name="scan_comparison_link_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_link_results_comparison_build_id"),
        table_name="scan_comparison_link_results",
    )
    op.drop_index(
        op.f("ix_scan_comparison_link_results_change_state"),
        table_name="scan_comparison_link_results",
    )
    op.drop_index("ix_comparison_link_build_target", table_name="scan_comparison_link_results")
    op.drop_index("ix_comparison_link_build_source", table_name="scan_comparison_link_results")
    op.drop_index("ix_comparison_link_build_presence", table_name="scan_comparison_link_results")
    op.drop_index("ix_comparison_link_build_change", table_name="scan_comparison_link_results")
    op.drop_table("scan_comparison_link_results")
    op.drop_table("scan_comparison_summaries")
    op.drop_index(op.f("ix_scan_comparisons_website_property_id"), table_name="scan_comparisons")
    op.drop_index(op.f("ix_scan_comparisons_target_scan_id"), table_name="scan_comparisons")
    op.drop_index(op.f("ix_scan_comparisons_baseline_scan_id"), table_name="scan_comparisons")
    op.drop_index("ix_scan_comparison_site_created", table_name="scan_comparisons")
    op.drop_table("scan_comparisons")
    op.drop_index(
        op.f("ix_scan_comparison_builds_target_projection_build_id"),
        table_name="scan_comparison_builds",
    )
    op.drop_index(op.f("ix_scan_comparison_builds_status"), table_name="scan_comparison_builds")
    op.drop_index(
        op.f("ix_scan_comparison_builds_scan_comparison_id"), table_name="scan_comparison_builds"
    )
    op.drop_index(
        op.f("ix_scan_comparison_builds_coverage_state"), table_name="scan_comparison_builds"
    )
    op.drop_index(
        op.f("ix_scan_comparison_builds_comparison_version"), table_name="scan_comparison_builds"
    )
    op.drop_index(
        op.f("ix_scan_comparison_builds_comparison_checksum_sha256"),
        table_name="scan_comparison_builds",
    )
    op.drop_index(
        op.f("ix_scan_comparison_builds_baseline_projection_build_id"),
        table_name="scan_comparison_builds",
    )
    op.drop_index(
        "ix_comparison_build_comparison_version_status", table_name="scan_comparison_builds"
    )
    op.drop_table("scan_comparison_builds")
