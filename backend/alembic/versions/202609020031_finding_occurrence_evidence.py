"""Add ResourceOccurrence Finding evidence references.

Downgrade intentionally removes ResourceOccurrence pointers because the previous
schema cannot represent that evidence kind. Findings, assessments, and all other
typed evidence references remain retained.

Revision ID: 202609020031
Revises: 202609010030
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609020031"
down_revision: str | None = "202609010030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("finding_evidence_references") as batch_op:
        batch_op.drop_constraint("ck_finding_evidence_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_finding_evidence_kind",
            "evidence_kind IN ('resource_snapshot', 'resource_occurrence', 'scan')",
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM finding_evidence_references WHERE evidence_kind = 'resource_occurrence'"
        )
    )
    with op.batch_alter_table("finding_evidence_references") as batch_op:
        batch_op.drop_constraint("ck_finding_evidence_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_finding_evidence_kind",
            "evidence_kind IN ('resource_snapshot', 'scan')",
        )
