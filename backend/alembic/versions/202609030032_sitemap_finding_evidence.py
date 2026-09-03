"""Add immutable sitemap membership and composite Finding evidence.

Historical SourceRefresh rows are not backfilled because mutable Inventory rows
cannot reconstruct exact historical declarations. Downgrade intentionally removes
only source-entry-observation Finding pointers before dropping the evidence table;
all Findings, assessments, and older supported typed pointers remain.

Revision ID: 202609030032
Revises: 202609020031
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609030032"
down_revision: str | None = "202609020031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_refreshes") as batch_op:
        batch_op.add_column(sa.Column("sitemap_document_type", sa.String(32)))
        batch_op.add_column(
            sa.Column(
                "membership_materialized",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index(
            "ix_source_refreshes_membership_materialized",
            ["membership_materialized"],
            unique=False,
        )
        batch_op.create_index(
            "ix_source_refreshes_sitemap_document_type",
            ["sitemap_document_type"],
            unique=False,
        )
        batch_op.add_column(
            sa.Column(
                "child_refresh_ids_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )

    op.create_table(
        "source_entry_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_refresh_id",
            sa.Integer(),
            sa.ForeignKey("source_refreshes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("web_resources.id")),
        sa.Column("raw_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text()),
        sa.Column("normalization_version", sa.String(64), nullable=False),
        sa.Column("sitemap_lastmod", sa.Text()),
        sa.Column("sitemap_changefreq", sa.String(32)),
        sa.Column("sitemap_priority", sa.String(32)),
        sa.Column("source_metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("validation_state", sa.String(32), nullable=False),
        sa.Column("validation_message", sa.Text()),
        sa.Column("scope_decision", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "source_refresh_id", "position", name="uq_source_entry_observation_position"
        ),
    )
    op.create_index(
        "ix_source_entry_observations_source_refresh_id",
        "source_entry_observations",
        ["source_refresh_id"],
    )
    op.create_index(
        "ix_source_entry_observations_resource_id", "source_entry_observations", ["resource_id"]
    )
    op.create_index(
        "ix_source_entry_observations_normalized_url",
        "source_entry_observations",
        ["normalized_url"],
    )
    op.create_index(
        "ix_source_entry_observations_normalization_version",
        "source_entry_observations",
        ["normalization_version"],
    )
    op.create_index(
        "ix_source_entry_observations_validation_state",
        "source_entry_observations",
        ["validation_state"],
    )
    op.create_index(
        "ix_source_entry_observations_scope_decision",
        "source_entry_observations",
        ["scope_decision"],
    )
    op.create_index(
        "ix_source_entry_observation_refresh_resource",
        "source_entry_observations",
        ["source_refresh_id", "resource_id"],
    )

    with op.batch_alter_table("finding_evaluations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "evidence_manifest_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            )
        )

    with op.batch_alter_table("finding_evidence_references") as batch_op:
        batch_op.drop_constraint("ck_finding_evidence_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_finding_evidence_kind",
            "evidence_kind IN ('resource_snapshot', 'resource_occurrence', "
            "'source_entry_observation', 'scan')",
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM finding_evidence_references "
            "WHERE evidence_kind = 'source_entry_observation'"
        )
    )
    with op.batch_alter_table("finding_evidence_references") as batch_op:
        batch_op.drop_constraint("ck_finding_evidence_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_finding_evidence_kind",
            "evidence_kind IN ('resource_snapshot', 'resource_occurrence', 'scan')",
        )

    with op.batch_alter_table("finding_evaluations") as batch_op:
        batch_op.drop_column("evidence_manifest_json")

    op.drop_table("source_entry_observations")
    with op.batch_alter_table("source_refreshes") as batch_op:
        batch_op.drop_column("child_refresh_ids_json")
        batch_op.drop_index("ix_source_refreshes_sitemap_document_type")
        batch_op.drop_index("ix_source_refreshes_membership_materialized")
        batch_op.drop_column("membership_materialized")
        batch_op.drop_column("sitemap_document_type")
