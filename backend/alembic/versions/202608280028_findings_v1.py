"""Add first-class Findings V1.

Revision ID: 202608280028
Revises: 202608270027
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608280028"
down_revision: str | None = "202608270027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBJECT_PREFIX = (
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
    "AND website_property_id IS NOT NULL AND job_type IN "
)


def _job_subject_constraint(site_types: str) -> str:
    return f"{_SUBJECT_PREFIX}({site_types}))"


def upgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            _job_subject_constraint(
                "'category_rule_evaluation', 'structured_content_build', 'finding_evaluation'"
            ),
        )

    op.create_table(
        "finding_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "website_property_id",
            sa.Integer(),
            sa.ForeignKey("website_properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_scan_id", sa.Integer(), sa.ForeignKey("scans.id", ondelete="SET NULL")),
        sa.Column("evaluator_version", sa.String(64), nullable=False),
        sa.Column("detector_bundle_identity", sa.String(128), nullable=False),
        sa.Column("input_fingerprint_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("evidence_horizon_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_page_count", sa.Integer(), nullable=False),
        sa.Column("active_page_universe_sha256", sa.String(64), nullable=False),
        sa.Column("active_page_resource_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("detected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clear_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reopened_finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assessment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluation_checksum_sha256", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_finding_evaluation_status",
        ),
    )
    op.create_index(
        "ix_finding_evaluations_website_property_id", "finding_evaluations", ["website_property_id"]
    )
    op.create_index(
        "ix_finding_evaluations_source_scan_id", "finding_evaluations", ["source_scan_id"]
    )
    op.create_index(
        "ix_finding_evaluations_evidence_horizon_at", "finding_evaluations", ["evidence_horizon_at"]
    )
    op.create_index("ix_finding_evaluations_status", "finding_evaluations", ["status"])
    op.create_index(
        "ix_finding_evaluations_site_horizon",
        "finding_evaluations",
        ["website_property_id", "evidence_horizon_at", "id"],
    )

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "website_property_id",
            sa.Integer(),
            sa.ForeignKey("website_properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "web_resource_id", sa.Integer(), sa.ForeignKey("web_resources.id"), nullable=False
        ),
        sa.Column("finding_type", sa.String(64), nullable=False),
        sa.Column("logical_key_version", sa.String(64), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("condition_state", sa.String(24), nullable=False),
        sa.Column("current_severity", sa.String(16)),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_evaluated_evidence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("reopened_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("current_assessment_id", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "condition_state IN ('detected', 'unknown', 'resolved')",
            name="ck_finding_condition_state",
        ),
        sa.CheckConstraint(
            "current_severity IS NULL OR current_severity IN ('medium', 'high')",
            name="ck_finding_current_severity",
        ),
        sa.UniqueConstraint(
            "website_property_id",
            "finding_type",
            "logical_key_version",
            "web_resource_id",
            name="uq_finding_logical_identity",
        ),
    )
    for column in (
        "website_property_id",
        "web_resource_id",
        "finding_type",
        "condition_state",
        "current_severity",
        "acknowledged_at",
        "current_assessment_id",
    ):
        op.create_index(f"ix_findings_{column}", "findings", [column])
    op.create_index(
        "ix_findings_site_state", "findings", ["website_property_id", "condition_state"]
    )

    op.create_table(
        "finding_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "finding_id",
            sa.Integer(),
            sa.ForeignKey("findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "finding_evaluation_id",
            sa.Integer(),
            sa.ForeignKey("finding_evaluations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16)),
        sa.Column("evidence_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("assessment_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "outcome IN ('detected', 'clear', 'unknown')", name="ck_finding_assessment_outcome"
        ),
        sa.CheckConstraint(
            "severity IS NULL OR severity IN ('medium', 'high')",
            name="ck_finding_assessment_severity",
        ),
        sa.UniqueConstraint(
            "finding_id", "finding_evaluation_id", name="uq_finding_assessment_evaluation"
        ),
        sa.UniqueConstraint("assessment_sha256", name="uq_finding_assessment_sha256"),
    )
    op.create_index("ix_finding_assessments_finding_id", "finding_assessments", ["finding_id"])
    op.create_index(
        "ix_finding_assessments_finding_evaluation_id",
        "finding_assessments",
        ["finding_evaluation_id"],
    )
    op.create_index("ix_finding_assessments_outcome", "finding_assessments", ["outcome"])
    op.create_index(
        "ix_finding_assessments_evidence_observed_at",
        "finding_assessments",
        ["evidence_observed_at"],
    )

    op.create_table(
        "finding_evidence_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "finding_assessment_id",
            sa.Integer(),
            sa.ForeignKey("finding_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("evidence_kind", sa.String(32), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("evidence_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('resource_snapshot', 'scan')", name="ck_finding_evidence_kind"
        ),
        sa.UniqueConstraint(
            "finding_assessment_id", "position", name="uq_finding_evidence_position"
        ),
    )
    op.create_index(
        "ix_finding_evidence_references_finding_assessment_id",
        "finding_evidence_references",
        ["finding_assessment_id"],
    )
    op.create_index(
        "ix_finding_evidence_references_evidence_kind",
        "finding_evidence_references",
        ["evidence_kind"],
    )
    op.create_index(
        "ix_finding_evidence_references_evidence_id", "finding_evidence_references", ["evidence_id"]
    )
    op.create_index(
        "ix_finding_evidence_pointer",
        "finding_evidence_references",
        ["evidence_kind", "evidence_id"],
    )


def downgrade() -> None:
    op.drop_table("finding_evidence_references")
    op.drop_table("finding_assessments")
    op.drop_table("findings")
    op.drop_table("finding_evaluations")
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            _job_subject_constraint("'category_rule_evaluation', 'structured_content_build'"),
        )
