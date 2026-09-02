"""Add persisted Finding detector summaries.

Revision ID: 202609010030
Revises: 202608310029
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609010030"
down_revision: str | None = "202608310029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("finding_evaluations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "detector_summary_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("finding_evaluations") as batch_op:
        batch_op.drop_column("detector_summary_json")
