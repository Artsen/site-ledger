"""Add Collection Plans refresh and freshness provenance.

Revision ID: 202609040033
Revises: 202609030032
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609040033"
down_revision: str | None = "202609030032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "collection_plans",
        sa.Column("active_collection_count_at_creation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "collection_plans",
        sa.Column("missing_count_at_creation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "collection_plans",
        sa.Column("selection_reason_counts_json", sa.JSON(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE collection_plans
            SET active_collection_count_at_creation = in_flight_count_at_creation,
                missing_count_at_creation = target_count,
                selection_reason_counts_json = json_object('missing_current', target_count)
            """
        )
    )
    with op.batch_alter_table("collection_plans") as batch:
        batch.alter_column("active_collection_count_at_creation", nullable=False)
        batch.alter_column("missing_count_at_creation", nullable=False)
        batch.alter_column("selection_reason_counts_json", nullable=False)
        batch.drop_constraint("ck_collection_plan_target_mode", type_="check")
        batch.create_check_constraint(
            "ck_collection_plan_target_mode",
            "target_mode IN ('missing_current', 'refresh_current')",
        )
    op.add_column(
        "collection_plan_targets",
        sa.Column("latest_compatible_observed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # V1 cannot represent refresh Plans, so only those V2 orchestration rows are discarded.
    op.execute(
        sa.text(
            """
            DELETE FROM collection_plan_batches
            WHERE collection_plan_id IN (
                SELECT id FROM collection_plans WHERE target_mode = 'refresh_current'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM collection_plan_targets
            WHERE collection_plan_id IN (
                SELECT id FROM collection_plans WHERE target_mode = 'refresh_current'
            )
            """
        )
    )
    op.execute(sa.text("DELETE FROM collection_plans WHERE target_mode = 'refresh_current'"))
    with op.batch_alter_table("collection_plan_targets") as batch:
        batch.drop_column("latest_compatible_observed_at")
    with op.batch_alter_table("collection_plans") as batch:
        batch.drop_constraint("ck_collection_plan_target_mode", type_="check")
        batch.create_check_constraint(
            "ck_collection_plan_target_mode", "target_mode = 'missing_current'"
        )
        batch.drop_column("selection_reason_counts_json")
        batch.drop_column("missing_count_at_creation")
        batch.drop_column("active_collection_count_at_creation")
