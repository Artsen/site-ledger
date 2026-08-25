"""add Page and URL Inventory removal lifecycle

Revision ID: 202608250024
Revises: 202608140023
Create Date: 2026-08-25 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608250024"
down_revision: str | None = "202608140023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("site_pages") as batch:
        batch.add_column(
            sa.Column(
                "workspace_state",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            )
        )
        batch.add_column(sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(
            "ck_site_page_workspace_state", "workspace_state IN ('active', 'suppressed')"
        )
        batch.create_index("ix_site_pages_workspace_state", ["workspace_state"])
        batch.create_index(
            "ix_site_page_site_workspace", ["website_property_id", "workspace_state"]
        )

    op.create_table(
        "site_inventory_suppressions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_property_id", sa.Integer(), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_value", sa.Text(), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_kind IN ('normalized_url', 'raw_url')",
            name="ck_site_inventory_suppression_target_kind",
        ),
        sa.ForeignKeyConstraint(
            ["website_property_id"], ["website_properties.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_property_id",
            "target_kind",
            "target_value",
            name="uq_site_inventory_suppression_target",
        ),
    )
    op.create_index(
        "ix_site_inventory_suppressions_website_property_id",
        "site_inventory_suppressions",
        ["website_property_id"],
    )
    op.create_index(
        "ix_site_inventory_suppression_lookup",
        "site_inventory_suppressions",
        ["website_property_id", "target_kind", "target_value"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_inventory_suppression_lookup", table_name="site_inventory_suppressions")
    op.drop_index(
        "ix_site_inventory_suppressions_website_property_id",
        table_name="site_inventory_suppressions",
    )
    op.drop_table("site_inventory_suppressions")
    with op.batch_alter_table("site_pages") as batch:
        batch.drop_index("ix_site_page_site_workspace")
        batch.drop_index("ix_site_pages_workspace_state")
        batch.drop_constraint("ck_site_page_workspace_state", type_="check")
        batch.drop_column("suppressed_at")
        batch.drop_column("workspace_state")
