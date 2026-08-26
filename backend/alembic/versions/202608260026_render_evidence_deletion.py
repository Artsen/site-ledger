"""add rendered evidence deletion marker

Revision ID: 202608260026
Revises: 202608260025
Create Date: 2026-08-26 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608260026"
down_revision: str | None = "202608260025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "render_run_targets",
        sa.Column("evidence_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("render_run_targets", "evidence_deleted_at")
