"""Add versioned structured Page content artifacts.

Revision ID: 202608070020
Revises: 202608070019
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608070020"
down_revision: str | None = "202608070019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL "
            "AND scan_comparison_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL "
            "AND scan_comparison_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL "
            "AND scan_comparison_id IS NOT NULL AND job_type = 'scan_comparison_build') OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
            "AND website_property_id IS NOT NULL "
            "AND job_type IN ('category_rule_evaluation', 'structured_content_build'))",
        )
    op.create_table(
        "html_structured_content_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "content_blob_id",
            sa.Integer(),
            sa.ForeignKey("content_blobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extractor_version", sa.String(64), nullable=False),
        sa.Column("extractor_config_version", sa.String(64), nullable=False),
        sa.Column("extraction_state", sa.String(32), nullable=False),
        sa.Column("document_profile", sa.String(32), nullable=False),
        sa.Column("section_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heading_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heading_counts_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("document_word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document_character_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document_text_sha256", sa.String(64), nullable=False),
        sa.Column("outline_sha256", sa.String(64), nullable=False),
        sa.Column("is_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("truncation_reasons_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "content_blob_id",
            "extractor_version",
            "extractor_config_version",
            name="uq_html_structured_content_artifact_identity",
        ),
    )
    op.create_index(
        "ix_html_structured_content_artifacts_content_blob_id",
        "html_structured_content_artifacts",
        ["content_blob_id"],
    )
    op.create_index(
        "ix_html_structured_content_artifacts_extraction_state",
        "html_structured_content_artifacts",
        ["extraction_state"],
    )
    op.create_index(
        "ix_html_structured_content_artifacts_document_profile",
        "html_structured_content_artifacts",
        ["document_profile"],
    )
    op.create_index(
        "ix_html_structured_content_artifacts_document_text_sha256",
        "html_structured_content_artifacts",
        ["document_text_sha256"],
    )
    op.create_index(
        "ix_html_structured_content_artifacts_outline_sha256",
        "html_structured_content_artifacts",
        ["outline_sha256"],
    )
    op.create_index(
        "ix_html_structured_content_artifacts_is_truncated",
        "html_structured_content_artifacts",
        ["is_truncated"],
    )
    op.create_index(
        "ix_html_structured_content_artifacts_blob_state",
        "html_structured_content_artifacts",
        ["content_blob_id", "extraction_state"],
    )

    op.create_table(
        "html_structured_content_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("html_structured_content_artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_section_id",
            sa.Integer(),
            sa.ForeignKey("html_structured_content_sections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.Column("heading_text", sa.Text(), nullable=True),
        sa.Column("heading_dom_path", sa.Text(), nullable=True),
        sa.Column("region_key", sa.String(32), nullable=False),
        sa.Column("region_dom_path", sa.Text(), nullable=True),
        sa.Column("direct_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("direct_text_sha256", sa.String(64), nullable=False),
        sa.Column("section_sha256", sa.String(64), nullable=False),
        sa.Column("subtree_sha256", sa.String(64), nullable=False),
        sa.Column("direct_word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("direct_character_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subtree_word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subtree_character_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("child_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("descendant_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("block_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_direct_content", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("artifact_id", "position", name="uq_structured_section_position"),
        sa.CheckConstraint(
            "heading_level IS NULL OR (heading_level >= 1 AND heading_level <= 6)",
            name="ck_structured_section_heading_level",
        ),
    )
    op.create_index(
        "ix_html_structured_content_sections_artifact_id",
        "html_structured_content_sections",
        ["artifact_id"],
    )
    op.create_index(
        "ix_html_structured_content_sections_parent_section_id",
        "html_structured_content_sections",
        ["parent_section_id"],
    )
    op.create_index(
        "ix_html_structured_content_sections_kind",
        "html_structured_content_sections",
        ["kind"],
    )
    op.create_index(
        "ix_html_structured_content_sections_region_key",
        "html_structured_content_sections",
        ["region_key"],
    )
    for column in ("direct_text_sha256", "section_sha256", "subtree_sha256"):
        op.create_index(
            f"ix_html_structured_content_sections_{column}",
            "html_structured_content_sections",
            [column],
        )
    op.create_index(
        "ix_html_structured_content_sections_artifact_position",
        "html_structured_content_sections",
        ["artifact_id", "position"],
    )


def downgrade() -> None:
    op.drop_table("html_structured_content_sections")
    op.drop_table("html_structured_content_artifacts")
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("ck_background_job_one_subject", type_="check")
        batch.create_check_constraint(
            "ck_background_job_one_subject",
            "(scan_id IS NOT NULL AND source_refresh_id IS NULL "
            "AND scan_comparison_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NOT NULL "
            "AND scan_comparison_id IS NULL) OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL "
            "AND scan_comparison_id IS NOT NULL AND job_type = 'scan_comparison_build') OR "
            "(scan_id IS NULL AND source_refresh_id IS NULL AND scan_comparison_id IS NULL "
            "AND website_property_id IS NOT NULL "
            "AND job_type = 'category_rule_evaluation')",
        )
