"""Separate exact, normalized, document, metadata, and technical Page signals.

Revision ID: 202608070019
Revises: 202608060018
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608070019"
down_revision: str | None = "202608060018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        sa.Column(
            "exact_source_state", sa.String(length=32), nullable=False, server_default="unavailable"
        ),
        sa.Column("exact_source_changed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("baseline_normalized_source_hash", sa.String(length=64), nullable=True),
        sa.Column("target_normalized_source_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "normalized_source_state",
            sa.String(length=32),
            nullable=False,
            server_default="unavailable",
        ),
        sa.Column(
            "document_content_state",
            sa.String(length=32),
            nullable=False,
            server_default="unavailable",
        ),
        sa.Column(
            "metadata_state", sa.String(length=32), nullable=False, server_default="unavailable"
        ),
        sa.Column(
            "technical_state", sa.String(length=32), nullable=False, server_default="unavailable"
        ),
        sa.Column(
            "primary_change_class",
            sa.String(length=32),
            nullable=False,
            server_default="indeterminate",
        ),
        sa.Column(
            "normalization_only_changed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "source_difference_categories_json", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("normalization_details_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    with op.batch_alter_table("scan_comparison_page_results") as batch:
        for column in columns:
            batch.add_column(column)
        for name in (
            "exact_source_state",
            "normalized_source_state",
            "document_content_state",
            "metadata_state",
            "technical_state",
            "primary_change_class",
        ):
            batch.create_index(f"ix_scan_comparison_page_results_{name}", [name])


def downgrade() -> None:
    with op.batch_alter_table("scan_comparison_page_results") as batch:
        for name in (
            "primary_change_class",
            "technical_state",
            "metadata_state",
            "document_content_state",
            "normalized_source_state",
            "exact_source_state",
        ):
            batch.drop_index(f"ix_scan_comparison_page_results_{name}")
        for name in (
            "normalization_details_json",
            "source_difference_categories_json",
            "normalization_only_changed",
            "primary_change_class",
            "technical_state",
            "metadata_state",
            "document_content_state",
            "normalized_source_state",
            "target_normalized_source_hash",
            "baseline_normalized_source_hash",
            "exact_source_changed",
            "exact_source_state",
        ):
            batch.drop_column(name)
